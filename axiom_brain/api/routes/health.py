"""
AxiomBrain — GET /health  &  GET /stats
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from axiom_brain.api.auth import require_api_key
from axiom_brain.api.schemas import HealthResponse, StatsResponse, TableStats
from axiom_brain.config import get_settings
from axiom_brain.database.connection import check_connectivity, get_pool

router = APIRouter()

_TABLES = ("thoughts", "people", "projects", "ideas", "admin")


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health() -> HealthResponse:
    db_ok = await check_connectivity()
    settings = get_settings()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=settings.app_version,
        db_ok=db_ok,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Row counts and last-update timestamps for all tables",
)
async def stats(_: str = Depends(require_api_key)) -> StatsResponse:
    pool  = await get_pool()
    db_ok = await check_connectivity()

    table_stats = []
    async with pool.acquire() as conn:
        for table in _TABLES:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) AS cnt, MAX(created_at) AS last_update FROM {table}"
            )
            table_stats.append(TableStats(
                table=table,
                row_count=row["cnt"],
                last_update=row["last_update"],
            ))

    return StatsResponse(tables=table_stats, db_ok=db_ok)
