"""
AxiomBrain — Decay Scoring

Provides two operations:
  1. record_access()       — called after every search to bump access_count
                             and refresh last_accessed_at for retrieved rows.
  2. recalculate_decay()   — called nightly to recompute all decay_score
                             values using the SQL procedure.

Decay model:
    decay_score = exp(-ln(2) / half_life_days * days_since_last_access)
    floored at 0.10 so memories never become completely invisible.

Half-lives by table:
    thoughts   30 days
    admin      14 days
    ideas      60 days
    people     90 days
    projects   90 days
"""

from __future__ import annotations

import logging
from typing import Dict, List
from uuid import UUID

logger = logging.getLogger(__name__)

# Half-life in days for each table — controls how fast memories decay
HALF_LIFE: Dict[str, float] = {
    "thoughts": 30.0,
    "admin":    14.0,
    "ideas":    60.0,
    "people":   90.0,
    "projects": 90.0,
}

DECAY_FLOOR = 0.10   # minimum decay_score — memories never completely vanish
DECAY_WEIGHT_FLOOR = 0.20  # floor used inside match_* SQL functions for ranking


# ─────────────────────────────────────────────────────────────────────────────
# Access recording
# ─────────────────────────────────────────────────────────────────────────────

async def record_access(
    conn,
    table: str,
    ids:   List[UUID],
) -> None:
    """
    Bump access_count and refresh last_accessed_at for the given row IDs.

    Called fire-and-forget after every search so that recently retrieved
    memories decay more slowly.  Safe to swallow errors — access tracking
    is best-effort and should never break search.
    """
    if not ids or table not in HALF_LIFE:
        return

    try:
        await conn.execute(
            f"""
            UPDATE {table}
            SET    access_count     = access_count + 1,
                   last_accessed_at = NOW()
            WHERE  id = ANY($1::uuid[])
            """,
            [str(i) for i in ids],
        )
    except Exception as exc:
        logger.warning("record_access(%s, %d ids) failed: %s", table, len(ids), exc)


async def record_access_multi(
    conn,
    hits: Dict[str, List[UUID]],
) -> None:
    """
    Record access for multiple tables at once.

    Args:
        hits: mapping of table_name → list of retrieved UUIDs
    """
    for table, ids in hits.items():
        await record_access(conn, table, ids)


# ─────────────────────────────────────────────────────────────────────────────
# Bulk recalculation
# ─────────────────────────────────────────────────────────────────────────────

async def recalculate_decay(conn) -> Dict[str, int]:
    """
    Call the SQL procedure that recomputes decay_score for all rows in all
    five tables.  Returns a dict of table → rows updated for logging.
    """
    counts: Dict[str, int] = {}

    try:
        await conn.execute("CALL recalculate_all_decay()")
        logger.info("recalculate_all_decay() complete")

        # Fetch row counts for the job report
        for table in HALF_LIFE:
            n = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            counts[table] = n

    except Exception as exc:
        logger.error("recalculate_decay failed: %s", exc, exc_info=True)
        raise

    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Utility: explain a single memory's decay state (for debugging / UI)
# ─────────────────────────────────────────────────────────────────────────────

async def get_decay_info(conn, table: str, memory_id: UUID) -> Dict:
    """
    Return decay metadata for a single memory row.
    Useful for the Web UI and for debugging.
    """
    if table not in HALF_LIFE:
        raise ValueError(f"Unknown table: {table!r}")

    row = await conn.fetchrow(
        f"""
        SELECT decay_score, access_count, last_accessed_at, created_at
        FROM   {table}
        WHERE  id = $1
        """,
        memory_id,
    )
    if not row:
        return {}

    return {
        "table":            table,
        "id":               str(memory_id),
        "decay_score":      row["decay_score"],
        "access_count":     row["access_count"],
        "last_accessed_at": row["last_accessed_at"],
        "created_at":       row["created_at"],
        "half_life_days":   HALF_LIFE[table],
    }
