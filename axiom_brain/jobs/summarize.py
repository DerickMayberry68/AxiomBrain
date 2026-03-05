"""
AxiomBrain — Summarization Job Runner

Orchestrates all three summary modes in a single pass:
  1. daily_thoughts  — compress unsummarized thoughts from the last 24 h
  2. project_rollup  — re-summarize every active project
  3. person_profile  — re-summarize every person who has been seen recently

Designed to be called:
  • On a nightly APScheduler cron (wired into FastAPI lifespan in main.py)
  • Via POST /summarize  (on-demand trigger from the API or MCP)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from axiom_brain.database.connection import get_pool
from axiom_brain.memory.embedder import Embedder
from axiom_brain.memory.summarizer import (
    save_summary,
    summarize_daily_thoughts,
    summarize_person,
    summarize_project,
)
from axiom_brain.notifications.teams import notify_summary_complete

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_all_active_workspaces(conn) -> List[Dict[str, Any]]:
    """Return id, name, and slug for every active workspace."""
    rows = await conn.fetch(
        "SELECT id, name, slug FROM workspaces WHERE is_active = TRUE ORDER BY created_at"
    )
    return [dict(r) for r in rows]


async def _get_active_project_ids(conn, workspace_id: Optional[UUID] = None) -> List[UUID]:
    if workspace_id is not None:
        rows = await conn.fetch(
            "SELECT id FROM projects WHERE status = 'active' AND workspace_id = $1 ORDER BY updated_at DESC",
            workspace_id,
        )
    else:
        rows = await conn.fetch(
            "SELECT id FROM projects WHERE status = 'active' ORDER BY updated_at DESC"
        )
    return [r["id"] for r in rows]


async def _get_recent_person_ids(conn, days: int = 30, workspace_id: Optional[UUID] = None) -> List[UUID]:
    if workspace_id is not None:
        rows = await conn.fetch(
            """
            SELECT DISTINCT p.id
            FROM   people p
            WHERE  p.last_seen >= NOW() - ($1 || ' days')::interval
              AND  p.workspace_id = $2
            ORDER  BY p.id
            """,
            str(days),
            workspace_id,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT DISTINCT p.id
            FROM   people p
            WHERE  p.last_seen >= NOW() - ($1 || ' days')::interval
            ORDER  BY p.id
            """,
            str(days),
        )
    return [r["id"] for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Single-workspace pass (shared by both on-demand and nightly paths)
# ─────────────────────────────────────────────────────────────────────────────

async def _run_for_workspace(
    conn,
    embedder:         Embedder,
    hours_back:       int,
    min_thought_count: int,
    workspace_id:     Optional[UUID],
) -> Dict[str, Any]:
    """
    Run all three summary modes for a single workspace (or globally when
    workspace_id is None).  Returns a partial results dict.
    """
    results: Dict[str, Any] = {
        "daily":    {"created": False, "summary_id": None},
        "projects": [],
        "people":   [],
        "errors":   [],
    }

    # ── 1. Daily thoughts digest ─────────────────────────────────────────────
    try:
        daily = await summarize_daily_thoughts(
            conn,
            hours_back=hours_back,
            min_count=min_thought_count,
            workspace_id=workspace_id,
        )
        if daily:
            sid = await save_summary(conn, daily, embedder)
            results["daily"]["created"]    = True
            results["daily"]["summary_id"] = sid
            logger.info("Daily summary created: %s (workspace=%s)", sid, workspace_id)
        else:
            logger.info("Daily summary skipped (not enough new thoughts) workspace=%s", workspace_id)
    except Exception as exc:
        logger.error("Daily summary failed (workspace=%s): %s", workspace_id, exc, exc_info=True)
        results["errors"].append({"type": "daily", "error": str(exc)})

    # ── 2. Active project rollups ─────────────────────────────────────────────
    try:
        project_ids = await _get_active_project_ids(conn, workspace_id=workspace_id)
        logger.info("Summarizing %d active projects (workspace=%s)", len(project_ids), workspace_id)
        for pid in project_ids:
            try:
                proj = await summarize_project(conn, pid, workspace_id=workspace_id)
                if proj:
                    sid = await save_summary(conn, proj, embedder)
                    results["projects"].append({"project_id": pid, "summary_id": sid})
                    logger.info("Project summary created for %s: %s", pid, sid)
            except Exception as exc:
                logger.error("Project %s summary failed: %s", pid, exc, exc_info=True)
                results["errors"].append({"type": "project", "id": str(pid), "error": str(exc)})
    except Exception as exc:
        logger.error("Project enumeration failed (workspace=%s): %s", workspace_id, exc, exc_info=True)
        results["errors"].append({"type": "project_enum", "error": str(exc)})

    # ── 3. Recent person profiles ─────────────────────────────────────────────
    try:
        person_ids = await _get_recent_person_ids(conn, days=30, workspace_id=workspace_id)
        logger.info("Summarizing %d recent people (workspace=%s)", len(person_ids), workspace_id)
        for person_id in person_ids:
            try:
                person = await summarize_person(conn, person_id, workspace_id=workspace_id)
                if person:
                    sid = await save_summary(conn, person, embedder)
                    results["people"].append({"person_id": person_id, "summary_id": sid})
                    logger.info("Person summary created for %s: %s", person_id, sid)
            except Exception as exc:
                logger.error("Person %s summary failed: %s", person_id, exc, exc_info=True)
                results["errors"].append({"type": "person", "id": str(person_id), "error": str(exc)})
    except Exception as exc:
        logger.error("Person enumeration failed (workspace=%s): %s", workspace_id, exc, exc_info=True)
        results["errors"].append({"type": "person_enum", "error": str(exc)})

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Main job entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_summarization_job(
    hours_back:        int            = 24,
    min_thought_count: int            = 3,
    workspace_id:      Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Run the full summarization pipeline.

    workspace_id behaviour:
      Provided  — on-demand call from a specific workspace (POST /summarize).
                  Runs only for that workspace.
      Omitted   — nightly scheduler call. Enumerates all active workspaces
                  and runs a pass for each; results are aggregated.

    Returns a results dict describing what was created:
        {
          "daily":    {"created": bool, "summary_id": UUID | None},
          "projects": [{"project_id": UUID, "summary_id": UUID}, ...],
          "people":   [{"person_id":  UUID, "summary_id": UUID}, ...],
          "errors":   [...],
        }
    """
    embedder = Embedder()
    pool     = await get_pool()
    _started = time.monotonic()

    # Aggregate results across all workspace passes
    combined: Dict[str, Any] = {
        "daily":    {"created": False, "summary_id": None},
        "projects": [],
        "people":   [],
        "errors":   [],
    }

    async with pool.acquire() as conn:
        if workspace_id is not None:
            # ── On-demand: single workspace ───────────────────────────────────
            r = await _run_for_workspace(
                conn, embedder, hours_back, min_thought_count, workspace_id
            )
            combined = r
        else:
            # ── Nightly: iterate all active workspaces ────────────────────────
            workspaces = await _get_all_active_workspaces(conn)
            logger.info("Nightly summarization: %d active workspaces", len(workspaces))

            for ws in workspaces:
                ws_id   = ws["id"]
                ws_name = ws["name"]
                logger.info("Running summarization pass for workspace '%s' (%s)", ws_name, ws_id)
                r = await _run_for_workspace(
                    conn, embedder, hours_back, min_thought_count, ws_id
                )
                # Merge into combined — daily: take first created, accumulate the rest
                if r["daily"]["created"] and not combined["daily"]["created"]:
                    combined["daily"] = r["daily"]
                combined["projects"].extend(r["projects"])
                combined["people"].extend(r["people"])
                combined["errors"].extend(r["errors"])

    duration = time.monotonic() - _started
    logger.info(
        "Summarization job complete — daily=%s, projects=%d, people=%d, errors=%d (%.1fs)",
        combined["daily"]["created"],
        len(combined["projects"]),
        len(combined["people"]),
        len(combined["errors"]),
        duration,
    )

    # ── Notify Teams (fire-and-forget; never blocks or raises) ────────────────
    _stats = {
        "thoughts": {
            "summaries_created": 1 if combined["daily"]["created"] else 0,
            "thoughts_processed": 0,  # not tracked at job level
        },
        "projects": {"summaries_created": len(combined["projects"])},
        "people":   {"summaries_created": len(combined["people"])},
        "errors":   combined["errors"],
    }
    notify_summary_complete(_stats, duration_seconds=duration)

    return combined
