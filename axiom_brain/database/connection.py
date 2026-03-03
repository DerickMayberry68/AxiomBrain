"""
AxiomBrain — Database Connection
Async connection pool using asyncpg + pgvector support.
"""

from __future__ import annotations

import asyncpg
from asyncpg import Pool
from typing import Optional

from axiom_brain.config import get_settings

_pool: Optional[Pool] = None


async def get_pool() -> Pool:
    """Return the global connection pool, initialising it on first call."""
    global _pool
    if _pool is None:
        _pool = await _create_pool()
    return _pool


async def _create_pool() -> Pool:
    settings = get_settings()

    async def init_connection(conn: asyncpg.Connection) -> None:
        # Register the vector type so asyncpg knows how to encode/decode it
        await conn.execute("SET search_path TO public")
        # asyncpg needs a codec for the vector type returned by pgvector
        await conn.set_type_codec(
            "vector",
            encoder=lambda v: str(v),
            decoder=lambda v: [float(x) for x in v.strip("[]").split(",")],
            schema="public",
            format="text",
        )

    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        init=init_connection,
        command_timeout=30,
    )
    return pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def check_connectivity() -> bool:
    """Quick health check — returns True if the DB is reachable."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False
