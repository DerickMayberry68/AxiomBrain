"""
AxiomBrain — Workspace database helpers

Provides fast lookup of workspaces by API key with a short-lived in-memory
cache so we're not hitting the DB on every request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from axiom_brain.database.connection import get_pool

# Simple TTL cache: {api_key: (workspace_record, expires_at)}
_CACHE: dict[str, tuple["WorkspaceRecord", float]] = {}
_CACHE_TTL = 60.0  # seconds


@dataclass
class WorkspaceRecord:
    id:        UUID
    name:      str
    slug:      str
    is_admin:  bool
    is_active: bool


def _cache_get(api_key: str) -> Optional[WorkspaceRecord]:
    entry = _CACHE.get(api_key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    _CACHE.pop(api_key, None)
    return None


def _cache_set(api_key: str, ws: WorkspaceRecord) -> None:
    _CACHE[api_key] = (ws, time.monotonic() + _CACHE_TTL)


def invalidate_cache() -> None:
    """Clear the entire workspace cache. Call after create/deactivate."""
    _CACHE.clear()


# ── Public API ────────────────────────────────────────────────────────────────

async def lookup_workspace(api_key: str) -> Optional[WorkspaceRecord]:
    """
    Return the active workspace for the given API key, or None if not found.
    Results are cached for _CACHE_TTL seconds.
    """
    cached = _cache_get(api_key)
    if cached is not None:
        return cached

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, slug, is_admin, is_active
            FROM   workspaces
            WHERE  api_key  = $1
              AND  is_active = TRUE
            """,
            api_key,
        )

    if not row:
        return None

    ws = WorkspaceRecord(
        id       = row["id"],
        name     = row["name"],
        slug     = row["slug"],
        is_admin = row["is_admin"],
        is_active= row["is_active"],
    )
    _cache_set(api_key, ws)
    return ws


async def create_workspace(name: str, slug: str, api_key: str) -> WorkspaceRecord:
    """
    Create a new workspace. Raises ValueError if slug or api_key already exists.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO workspaces (name, slug, api_key, is_active, is_admin)
                VALUES ($1, $2, $3, TRUE, FALSE)
                RETURNING id, name, slug, is_admin, is_active
                """,
                name, slug, api_key,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ValueError(f"A workspace with that slug or API key already exists.") from exc
            raise

    return WorkspaceRecord(
        id       = row["id"],
        name     = row["name"],
        slug     = row["slug"],
        is_admin = row["is_admin"],
        is_active= row["is_active"],
    )


async def list_workspaces() -> List[dict]:
    """Return all workspaces (active and inactive) for admin views."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, slug, is_admin, is_active, created_at FROM workspaces ORDER BY created_at"
        )
    return [dict(r) for r in rows]


async def deactivate_workspace(workspace_id: UUID) -> bool:
    """
    Deactivate (soft-delete) a workspace by ID.
    Returns True if a row was updated, False if not found.
    Admin workspaces cannot be deactivated.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE workspaces
            SET    is_active = FALSE, updated_at = NOW()
            WHERE  id = $1 AND is_admin = FALSE
            """,
            workspace_id,
        )
    invalidate_cache()
    # asyncpg returns "UPDATE N" — parse N
    count = int(result.split()[-1])
    return count > 0
