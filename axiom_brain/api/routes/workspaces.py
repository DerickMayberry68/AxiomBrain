"""
AxiomBrain — Workspace management routes

GET  /workspaces/me          — return current workspace info (any key)
GET  /workspaces             — list all workspaces (admin only)
POST /workspaces             — create a new workspace (admin only)
DELETE /workspaces/{ws_id}   — deactivate a workspace (admin only, cannot deactivate self)
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from axiom_brain.api.auth import get_workspace, require_admin
from axiom_brain.database.workspace import (
    WorkspaceRecord,
    create_workspace,
    deactivate_workspace,
    list_workspaces,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class WorkspaceResponse(BaseModel):
    id:        UUID
    name:      str
    slug:      str
    is_admin:  bool
    is_active: bool


class WorkspaceDetailResponse(WorkspaceResponse):
    created_at: datetime


class WorkspacesListResponse(BaseModel):
    workspaces: List[WorkspaceDetailResponse]
    count:      int


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100,
                      description="Human-readable workspace name (e.g. 'Backend Team')")
    slug: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$",
                      description="URL-safe identifier (e.g. 'backend-team')")
    api_key: Optional[str] = Field(
        default=None,
        description="API key for this workspace. If omitted, a secure key is auto-generated.",
    )


class WorkspaceCreateResponse(BaseModel):
    workspace: WorkspaceResponse
    api_key:   str  # returned once at creation — not stored in plaintext after this


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=WorkspaceResponse)
async def get_my_workspace(
    workspace: WorkspaceRecord = Depends(get_workspace),
) -> WorkspaceResponse:
    """Return information about the workspace the current API key belongs to."""
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        is_admin=workspace.is_admin,
        is_active=workspace.is_active,
    )


@router.get("", response_model=WorkspacesListResponse)
async def list_all_workspaces(
    _admin: WorkspaceRecord = Depends(require_admin),
) -> WorkspacesListResponse:
    """List all workspaces. Requires an admin workspace key."""
    rows = await list_workspaces()
    items = [
        WorkspaceDetailResponse(
            id=r["id"],
            name=r["name"],
            slug=r["slug"],
            is_admin=r["is_admin"],
            is_active=r["is_active"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return WorkspacesListResponse(workspaces=items, count=len(items))


@router.post("", response_model=WorkspaceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_workspace(
    body:   WorkspaceCreateRequest,
    _admin: WorkspaceRecord = Depends(require_admin),
) -> WorkspaceCreateResponse:
    """
    Create a new workspace and return its API key.
    The API key is shown ONCE here — it is not retrievable later.
    Requires an admin workspace key.
    """
    api_key = body.api_key or secrets.token_urlsafe(32)

    try:
        ws = await create_workspace(
            name=body.name,
            slug=body.slug,
            api_key=api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return WorkspaceCreateResponse(
        workspace=WorkspaceResponse(
            id=ws.id,
            name=ws.name,
            slug=ws.slug,
            is_admin=ws.is_admin,
            is_active=ws.is_active,
        ),
        api_key=api_key,
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_a_workspace(
    workspace_id: UUID,
    admin: WorkspaceRecord = Depends(require_admin),
) -> None:
    """
    Deactivate a workspace (soft delete). Admin workspaces cannot be deactivated.
    Requires an admin workspace key.
    """
    if workspace_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own workspace.",
        )

    removed = await deactivate_workspace(workspace_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or is an admin workspace (cannot be deactivated).",
        )
