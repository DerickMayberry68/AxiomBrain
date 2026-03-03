"""
AxiomBrain — Decay Recalculation Job

Runs nightly (2:30 AM via APScheduler) to recompute decay_score on all rows
in all five memory tables.  Also exposed via POST /decay/recalculate so you
can trigger it on-demand without waiting for the scheduler.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from axiom_brain.database.connection import get_pool
from axiom_brain.memory.decay import recalculate_decay

logger = logging.getLogger(__name__)


async def run_decay_job() -> Dict[str, Any]:
    """
    Acquire a connection and call recalculate_decay().

    Returns:
        {
          "status":  "ok" | "error",
          "counts":  {"thoughts": N, "people": N, ...},
          "error":   str | None,
        }
    """
    pool = await get_pool()

    try:
        async with pool.acquire() as conn:
            counts = await recalculate_decay(conn)

        logger.info(
            "Decay job complete — %s",
            ", ".join(f"{t}={n}" for t, n in counts.items()),
        )
        return {"status": "ok", "counts": counts, "error": None}

    except Exception as exc:
        logger.error("Decay job failed: %s", exc, exc_info=True)
        return {"status": "error", "counts": {}, "error": str(exc)}
