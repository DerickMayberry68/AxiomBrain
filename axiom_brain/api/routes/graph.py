"""
AxiomBrain — Graph Relationship Routes (Neo4j backend)

POST   /relationships                        — create a manual edge
GET    /relationships/{table}/{node_id}      — get all edges for a node
DELETE /relationships/{edge_id}              — delete an edge by ID
GET    /graph/traverse/{table}/{node_id}     — multi-hop traversal (NEW)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from axiom_brain.api.auth import require_api_key
from axiom_brain.api.schemas import (
    RelationshipCreate,
    RelationshipResponse,
    RelationshipsListResponse,
)
from axiom_brain.memory.graph import create_edge, delete_edge, get_edges, traverse

router = APIRouter(tags=["Graph"])

_VALID_TABLES = ("thoughts", "people", "projects", "ideas", "admin")
_VALID_DIRS   = ("from", "to", "both")


def _parse_meta(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Existing endpoints (now backed by Neo4j, same contract)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/relationships",
    response_model=RelationshipResponse,
    status_code=201,
    summary="Create a manual relationship edge between two memory nodes",
)
async def create_relationship(
    body: RelationshipCreate,
    _:    str = Depends(require_api_key),
) -> RelationshipResponse:
    edge_id = await create_edge(
        conn          = None,
        from_table    = body.from_table,
        from_id       = body.from_id,
        to_table      = body.to_table,
        to_id         = body.to_id,
        rel_type      = body.rel_type,
        strength      = body.strength,
        auto_detected = False,
        source        = body.source or "api_manual",
        metadata      = body.metadata or {},
    )
    if edge_id is None:
        raise HTTPException(
            status_code=409,
            detail="Relationship already exists between these nodes with this type.",
        )

    return RelationshipResponse(
        id            = edge_id,
        from_table    = body.from_table,
        from_id       = body.from_id,
        to_table      = body.to_table,
        to_id         = body.to_id,
        rel_type      = body.rel_type,
        strength      = body.strength,
        auto_detected = False,
        source        = body.source or "api_manual",
        created_at    = __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        metadata      = body.metadata or {},
    )


@router.get(
    "/relationships/{table}/{node_id}",
    response_model=RelationshipsListResponse,
    summary="Get all edges connected to a memory node",
)
async def list_relationships(
    table:     str,
    node_id:   UUID,
    direction: str           = Query(default="both"),
    rel_type:  Optional[str] = Query(default=None),
    _:         str           = Depends(require_api_key),
) -> RelationshipsListResponse:
    if table not in _VALID_TABLES:
        raise HTTPException(status_code=422, detail=f"Invalid table: {table!r}")
    if direction not in _VALID_DIRS:
        raise HTTPException(status_code=422, detail=f"Invalid direction: {direction!r}")

    edges = await get_edges(
        conn      = None,
        table     = table,
        node_id   = node_id,
        direction = direction,
        rel_type  = rel_type or None,
    )

    return RelationshipsListResponse(
        node_table    = table,
        node_id       = node_id,
        direction     = direction,
        relationships = [
            RelationshipResponse(
                id            = e["id"],
                from_table    = e["from_table"],
                from_id       = e["from_id"],
                to_table      = e["to_table"],
                to_id         = e["to_id"],
                rel_type      = e["rel_type"],
                strength      = e["strength"],
                auto_detected = e["auto_detected"],
                source        = e["source"],
                created_at    = e["created_at"],
                metadata      = _parse_meta(e["metadata"]),
            )
            for e in edges
        ],
        count = len(edges),
    )


@router.delete(
    "/relationships/{edge_id}",
    status_code=204,
    summary="Delete a relationship edge by ID",
)
async def remove_relationship(
    edge_id: UUID,
    _:       str = Depends(require_api_key),
) -> None:
    deleted = await delete_edge(None, edge_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Relationship not found.")


# ─────────────────────────────────────────────────────────────────────────────
# Multi-hop traversal  (new — only possible with Neo4j)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/graph/traverse/{table}/{node_id}",
    summary="Multi-hop graph traversal — find all nodes within N hops",
)
async def graph_traverse(
    table:   str,
    node_id: UUID,
    hops:    int = Query(default=2, ge=1, le=5,
                         description="Maximum relationship hops (1–5)"),
    limit:   int = Query(default=50, ge=1, le=200),
    _:       str = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    Returns every node reachable from the given node within `hops` steps,
    along with the path taken to reach it.

    Example — 2 hops from a Person node reveals:
      • Projects they work on (1 hop)
      • Ideas that belong to those projects (2 hops)
      • Thoughts recorded in those projects (2 hops)
    """
    if table not in _VALID_TABLES:
        raise HTTPException(status_code=422, detail=f"Invalid table: {table!r}")

    paths = await traverse(table=table, node_id=node_id, hops=hops, limit=limit)

    # Deduplicate reachable nodes for a summary
    seen: Dict[str, Dict] = {}
    for path in paths:
        for node in path["path_nodes"]:
            key = node["id"]
            if key not in seen:
                seen[key] = node

    reachable = [v for v in seen.values() if v["id"] != str(node_id)]

    return {
        "start_table":      table,
        "start_node_id":    str(node_id),
        "hops":             hops,
        "reachable_count":  len(reachable),
        "reachable_nodes":  reachable,
        "paths":            paths,
    }
