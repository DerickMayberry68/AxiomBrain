"""
AxiomBrain — Summarization Routes

POST /summarize        — trigger full summarization pipeline (nightly job on-demand)
GET  /summaries        — list recent summaries (paginated, optional type filter)
GET  /summaries/{id}   — retrieve a specific summary by UUID
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from axiom_brain.api.auth import get_workspace
from axiom_brain.database.workspace import WorkspaceRecord
from axiom_brain.api.schemas import (
    SummarizeRequest,
    SummarizeResponse,
    SummariesListResponse,
    SummaryItem,
)
from axiom_brain.database.connection import get_pool
from axiom_brain.jobs.summarize import run_summarization_job

router = APIRouter(tags=["Summarization"])

_VALID_TYPES = ("daily_thoughts", "project_rollup", "person_profile", "all_tables")


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    summary="Trigger the summarization pipeline (on-demand or scheduled)",
)
async def trigger_summarize(
    body:      SummarizeRequest = SummarizeRequest(),
    workspace: WorkspaceRecord  = Depends(get_workspace),
) -> SummarizeResponse:
    """
    Run all three summary modes (daily thoughts, project rollups, person profiles).
    Scoped to the calling workspace — only that workspace's memories are summarized.
    Safe to call repeatedly — unsummarized thoughts are only consumed once.
    """
    results = await run_summarization_job(
        hours_back=body.hours_back,
        min_thought_count=body.min_thought_count,
        workspace_id=workspace.id,
    )

    # Flatten summary IDs for the response
    summary_ids: list[UUID] = []
    if results["daily"]["summary_id"]:
        summary_ids.append(results["daily"]["summary_id"])
    summary_ids.extend(r["summary_id"] for r in results["projects"])
    summary_ids.extend(r["summary_id"] for r in results["people"])

    return SummarizeResponse(
        daily_created=results["daily"]["created"],
        projects_summarized=len(results["projects"]),
        people_summarized=len(results["people"]),
        summary_ids=summary_ids,
        errors=results["errors"],
    )


@router.get(
    "/summaries",
    response_model=SummariesListResponse,
    summary="List recent summaries with optional type filter",
)
async def list_summaries(
    summary_type: Optional[str]  = Query(default=None, description="Filter by type: daily_thoughts | project_rollup | person_profile"),
    limit:        int            = Query(default=20, ge=1, le=100),
    offset:       int            = Query(default=0, ge=0),
    workspace:    WorkspaceRecord = Depends(get_workspace),
) -> SummariesListResponse:
    if summary_type and summary_type not in _VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid summary_type: {summary_type!r}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        if summary_type:
            rows = await conn.fetch(
                """
                SELECT id, summary_type, subject_name, content, source_count,
                       period_start, period_end, topics, created_at
                FROM   summaries
                WHERE  summary_type = $1
                  AND  workspace_id = $2
                ORDER  BY created_at DESC
                LIMIT  $3 OFFSET $4
                """,
                summary_type, workspace.id, limit, offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM summaries WHERE summary_type = $1 AND workspace_id = $2",
                summary_type, workspace.id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, summary_type, subject_name, content, source_count,
                       period_start, period_end, topics, created_at
                FROM   summaries
                WHERE  workspace_id = $1
                ORDER  BY created_at DESC
                LIMIT  $2 OFFSET $3
                """,
                workspace.id, limit, offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM summaries WHERE workspace_id = $1",
                workspace.id,
            )

    items = [
        SummaryItem(
            id           = r["id"],
            summary_type = r["summary_type"],
            subject_name = r["subject_name"],
            content      = r["content"],
            source_count = r["source_count"],
            period_start = r["period_start"],
            period_end   = r["period_end"],
            topics       = list(r["topics"] or []),
            created_at   = r["created_at"],
        )
        for r in rows
    ]

    return SummariesListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/summaries/{summary_id}",
    response_model=SummaryItem,
    summary="Retrieve a specific summary by UUID",
)
async def get_summary(
    summary_id: UUID,
    workspace:  WorkspaceRecord = Depends(get_workspace),
) -> SummaryItem:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, summary_type, subject_name, content, source_count,
                   period_start, period_end, topics, created_at
            FROM   summaries
            WHERE  id = $1
              AND  workspace_id = $2
            """,
            summary_id,
            workspace.id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Summary not found.")

    return SummaryItem(
        id           = row["id"],
        summary_type = row["summary_type"],
        subject_name = row["subject_name"],
        content      = row["content"],
        source_count = row["source_count"],
        period_start = row["period_start"],
        period_end   = row["period_end"],
        topics       = list(row["topics"] or []),
        created_at   = row["created_at"],
    )
