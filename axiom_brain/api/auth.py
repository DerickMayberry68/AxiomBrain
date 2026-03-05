"""
AxiomBrain — API Key Authentication

Two FastAPI dependencies are provided:

  get_workspace   — resolves the X-API-Key header to a WorkspaceRecord.
                    Use this on all data routes (ingest, search, graph, etc.)
                    so they're automatically scoped to the caller's workspace.

  require_api_key — lightweight variant that just validates the key and returns
                    it as a string. Kept for non-data routes (webhooks, health).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from axiom_brain.config import get_settings
from axiom_brain.database.workspace import WorkspaceRecord, lookup_workspace

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_workspace(api_key: str = Security(_api_key_header)) -> WorkspaceRecord:
    """
    FastAPI dependency — resolves the X-API-Key header to a WorkspaceRecord.
    Raises 401 if the key is missing, invalid, or the workspace is inactive.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )
    ws = await lookup_workspace(api_key)
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key.",
        )
    return ws


async def require_admin(ws: WorkspaceRecord = Depends(get_workspace)) -> WorkspaceRecord:
    """
    FastAPI dependency — same as get_workspace but additionally requires
    the workspace to have is_admin=True. Used for workspace management routes.
    """
    if not ws.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires an admin workspace key.",
        )
    return ws


async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """
    Lightweight dependency — validates the key exists in the workspaces table.
    Returns the raw key string. Use for non-data routes (webhooks, health checks).
    """
    settings = get_settings()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Set X-API-Key header.",
        )
    # Fast path: check against the configured master key first (no DB hit)
    if api_key == settings.axiom_api_key:
        return api_key
    # Otherwise, verify it's a valid workspace key
    ws = await lookup_workspace(api_key)
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Set X-API-Key header.",
        )
    return api_key
