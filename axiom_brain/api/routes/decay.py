"""
AxiomBrain — Decay Routes

POST /decay/recalculate   — trigger immediate decay score recalculation
GET  /decay/{table}/{id}  — inspect a single memory's decay state
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from axiom_brain.api.auth import require_api_key
from axiom_brain.database.connection import get_pool
from axiom_brain.memory.decay import get_decay_info, recalculate_decay
from axiom_brain.jobs.decay import run_decay_job

router = APIRouter(tags=["Decay"])

_VALID_TABLES = ("thoughts", "people", "projects", "ideas", "admin")


@router.post(
    "/decay/recalculate",
    summary="Recalculate decay scores for all memory tables",
)
async def trigger_recalculate(
    _: str = Depends(require_api_key),
):
    """
    Immediately recompute decay_score for every row in all five tables.
    Normally called by the nightly scheduler — use this for on-demand refresh.
    """
    result = await run_decay_job()
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get(
    "/decay/{table}/{memory_id}",
    summary="Inspect decay state for a single memory",
)
async def get_memory_decay(
    table:     str,
    memory_id: UUID,
    _:         str = Depends(require_api_key),
):
    """
    Returns decay_score, access_count, last_accessed_at, and half-life for
    a specific memory.  Useful for debugging why a memory ranks lower than
    expected.
    """
    if table not in _VALID_TABLES:
        raise HTTPException(status_code=422, detail=f"Invalid table: {table!r}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        info = await get_decay_info(conn, table, memory_id)

    if not info:
        raise HTTPException(status_code=404, detail="Memory not found.")

    return info
