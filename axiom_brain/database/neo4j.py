"""
AxiomBrain — Neo4j Async Driver

Manages a single AsyncGraphDatabase driver instance shared across the
FastAPI application lifetime.  Connect on first use; close during shutdown
via close_driver() wired into the FastAPI lifespan.

Usage:
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (n:Memory) RETURN count(n) AS cnt")
        record = await result.single()
        print(record["cnt"])
"""

from __future__ import annotations

import logging
from typing import Optional

from neo4j import AsyncDriver, AsyncGraphDatabase

from axiom_brain.config import get_settings

logger = logging.getLogger(__name__)

_driver: Optional[AsyncDriver] = None


async def get_driver() -> AsyncDriver:
    """Return (or lazily create) the shared Neo4j async driver."""
    global _driver
    if _driver is None:
        settings   = get_settings()
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=50,
        )
        logger.info("Neo4j driver connected → %s", settings.neo4j_uri)
        await _ensure_schema(_driver)
    return _driver


async def close_driver() -> None:
    """Close the driver — called during FastAPI lifespan shutdown."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


async def _ensure_schema(driver: AsyncDriver) -> None:
    """
    Create uniqueness constraint and indexes on first connect.
    These are idempotent — safe to run every startup.
    """
    async with driver.session() as session:
        # Uniqueness: each (id) is unique across all Memory nodes
        await session.run(
            "CREATE CONSTRAINT memory_id_unique IF NOT EXISTS "
            "FOR (n:Memory) REQUIRE n.id IS UNIQUE"
        )
        # Index on table property for fast per-table lookups
        await session.run(
            "CREATE INDEX memory_table_idx IF NOT EXISTS "
            "FOR (n:Memory) ON (n.table)"
        )
    logger.debug("Neo4j schema constraints/indexes verified")
