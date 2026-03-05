"""
AxiomBrain — POST /ingest
Runs the full embed → classify → route pipeline for a content item.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from axiom_brain.api.auth import get_workspace
from axiom_brain.api.schemas import IngestRequest, IngestResponse
from axiom_brain.database.workspace import WorkspaceRecord
from axiom_brain.memory.router import get_router

router = APIRouter()


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Store content in the brain",
    description=(
        "Accepts raw text content, runs embedding + LLM classification, "
        "and routes to the appropriate memory table. Always logs to the "
        "thoughts audit table regardless of routing."
    ),
)
async def ingest(
    body: IngestRequest,
    workspace: WorkspaceRecord = Depends(get_workspace),
) -> IngestResponse:
    memory_router = get_router()
    result = await memory_router.ingest(
        content=body.content,
        source=body.source,
        target_table=body.target_table,
        workspace_id=workspace.id,
    )
    return IngestResponse(
        thought_id=result.thought_id,
        routed_to=result.routed_to,
        routed_id=result.routed_id,
        content_type=result.content_type,
        confidence=result.confidence,
        topics=result.topics,
        people=result.people,
        action_items=result.action_items,
    )
