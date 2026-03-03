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
from typing import Any, Dict, List
from uuid import UUID

from axiom_brain.database.connection import get_pool
from axiom_brain.memory.embedder import Embedder
from axiom_brain.memory.summarizer import (
    save_summary,
    summarize_daily_thoughts,
    summarize_person,
    summarize_project,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_active_project_ids(conn) -> List[UUID]:
    rows = await conn.fetch(
        "SELECT id FROM projects WHERE status = 'active' ORDER BY updated_at DESC"
    )
    return [r["id"] for r in rows]


async def _get_recent_person_ids(conn, days: int = 30) -> List[UUID]:
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
# Main job entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_summarization_job(
    hours_back: int = 24,
    min_thought_count: int = 3,
) -> Dict[str, Any]:
    """
    Run the full summarization pipeline.

    Returns a results dict describing what was created:
        {
          "daily":    {"created": bool, "summary_id": UUID | None},
          "projects": [{"project_id": UUID, "summary_id": UUID}, ...],
          "people":   [{"person_id":  UUID, "summary_id": UUID}, ...],
          "errors":   [...],
        }
    """
    results: Dict[str, Any] = {
        "daily":    {"created": False, "summary_id": None},
        "projects": [],
        "people":   [],
        "errors":   [],
    }

    embedder = Embedder()
    pool     = await get_pool()

    async with pool.acquire() as conn:

        # ── 1. Daily thoughts digest ─────────────────────────────────────────
        try:
            daily = await summarize_daily_thoughts(
                conn,
                hours_back=hours_back,
                min_count=min_thought_count,
            )
            if daily:
                sid = await save_summary(conn, daily, embedder)
                results["daily"]["created"]    = True
                results["daily"]["summary_id"] = sid
                logger.info("Daily summary created: %s", sid)
            else:
                logger.info("Daily summary skipped (not enough new thoughts)")
        except Exception as exc:
            logger.error("Daily summary failed: %s", exc, exc_info=True)
            results["errors"].append({"type": "daily", "error": str(exc)})

        # ── 2. Active project rollups ────────────────────────────────────────
        try:
            project_ids = await _get_active_project_ids(conn)
            logger.info("Summarizing %d active projects", len(project_ids))
            for pid in project_ids:
                try:
                    proj = await summarize_project(conn, pid)
                    if proj:
                        sid = await save_summary(conn, proj, embedder)
                        results["projects"].append({"project_id": pid, "summary_id": sid})
                        logger.info("Project summary created for %s: %s", pid, sid)
                except Exception as exc:
                    logger.error("Project %s summary failed: %s", pid, exc, exc_info=True)
                    results["errors"].append({"type": "project", "id": str(pid), "error": str(exc)})
        except Exception as exc:
            logger.error("Project enumeration failed: %s", exc, exc_info=True)
            results["errors"].append({"type": "project_enum", "error": str(exc)})

        # ── 3. Recent person profiles ────────────────────────────────────────
        try:
            person_ids = await _get_recent_person_ids(conn, days=30)
            logger.info("Summarizing %d recent people", len(person_ids))
            for person_id in person_ids:
                try:
                    person = await summarize_person(conn, person_id)
                    if person:
                        sid = await save_summary(conn, person, embedder)
                        results["people"].append({"person_id": person_id, "summary_id": sid})
                        logger.info("Person summary created for %s: %s", person_id, sid)
                except Exception as exc:
                    logger.error("Person %s summary failed: %s", person_id, exc, exc_info=True)
                    results["errors"].append({"type": "person", "id": str(person_id), "error": str(exc)})
        except Exception as exc:
            logger.error("Person enumeration failed: %s", exc, exc_info=True)
            results["errors"].append({"type": "person_enum", "error": str(exc)})

    logger.info(
        "Summarization job complete — daily=%s, projects=%d, people=%d, errors=%d",
        results["daily"]["created"],
        len(results["projects"]),
        len(results["people"]),
        len(results["errors"]),
    )
    return results
