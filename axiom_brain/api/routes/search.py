"""
AxiomBrain — POST /search  &  GET /thoughts
Semantic search across memory tables, plus paginated thoughts log.
All results are scoped to the caller's workspace via the API key.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from axiom_brain.api.auth import get_workspace
from axiom_brain.api.schemas import (
    SearchRequest, SearchResponse, SearchResult,
    ThoughtItem, ThoughtsResponse,
)
from axiom_brain.config import get_settings
from axiom_brain.database.connection import get_pool
from axiom_brain.database.workspace import WorkspaceRecord
from axiom_brain.memory.decay import record_access_multi
from axiom_brain.memory.embedder import get_embedder

router = APIRouter()

_ALL_TABLES = ("thoughts", "people", "projects", "ideas", "admin")


async def _track_access(hits: Dict[str, List[UUID]]) -> None:
    """Fire-and-forget: bump access_count / last_accessed_at for returned rows."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await record_access_multi(conn, hits)
    except Exception:
        pass  # access tracking is best-effort — never break search


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Semantic search across the brain",
)
async def search(
    body:       SearchRequest,
    background: BackgroundTasks,
    workspace:  WorkspaceRecord = Depends(get_workspace),
) -> SearchResponse:
    embedder = get_embedder()
    pool     = await get_pool()

    query_vec = await embedder.embed(body.query)
    vec_str   = f"[{','.join(str(x) for x in query_vec)}]"

    tables_to_search = body.tables or list(_ALL_TABLES)
    results: List[SearchResult] = []

    async with pool.acquire() as conn:
        if set(tables_to_search) == set(_ALL_TABLES):
            rows = await conn.fetch(
                "SELECT * FROM search_all($1::vector, $2, $3)",
                vec_str, body.limit, workspace.id,
            )
            for row in rows:
                results.append(SearchResult(
                    source_table=row["source_table"],
                    id=row["id"],
                    primary_text=row["primary_text"],
                    topics=list(row["topics"] or []),
                    created_at=row["created_at"],
                    similarity=row["similarity"],
                ))
        else:
            per_table_limit = max(body.limit, 5)
            for table in tables_to_search:
                rows = await _search_table(
                    conn=conn,
                    table=table,
                    vec_str=vec_str,
                    limit=per_table_limit,
                    topic_filter=body.topic_filter,
                    person_filter=body.person_filter,
                    workspace_id=workspace.id,
                )
                results.extend(rows)

            results.sort(key=lambda r: r.similarity, reverse=True)
            results = results[: body.limit]

    # Record access in background — fire and forget, never blocks the response
    if results:
        hits: Dict[str, List[UUID]] = defaultdict(list)
        for r in results:
            hits[r.source_table].append(r.id)
        background.add_task(_track_access, dict(hits))

    return SearchResponse(query=body.query, results=results, count=len(results))


async def _search_table(
    conn,
    table: str,
    vec_str: str,
    limit: int,
    topic_filter: Optional[str],
    person_filter: Optional[str],
    workspace_id: Optional[UUID] = None,
) -> List[SearchResult]:
    """Call the appropriate match_* function for a given table."""
    results: List[SearchResult] = []

    if table == "thoughts":
        rows = await conn.fetch(
            "SELECT * FROM match_thoughts($1::vector, $2, $3, $4, $5)",
            vec_str, limit, topic_filter, person_filter, workspace_id,
        )
        for row in rows:
            results.append(SearchResult(
                source_table="thoughts",
                id=row["id"],
                primary_text=row["content"],
                topics=list(row["topics"] or []),
                created_at=row["created_at"],
                similarity=row["similarity"],
                metadata={
                    "content_type": row["content_type"],
                    "people": list(row["people"] or []),
                    "action_items": list(row["action_items"] or []),
                },
            ))

    elif table == "people":
        rows = await conn.fetch(
            "SELECT * FROM match_people($1::vector, $2, $3, $4)",
            vec_str, limit, topic_filter, workspace_id,
        )
        for row in rows:
            results.append(SearchResult(
                source_table="people",
                id=row["id"],
                primary_text=f"{row['name']}: {row['notes'] or ''}",
                topics=list(row["topics"] or []),
                created_at=row["last_seen"],
                similarity=row["similarity"],
                metadata={"name": row["name"]},
            ))

    elif table == "projects":
        rows = await conn.fetch(
            "SELECT * FROM match_projects($1::vector, $2, NULL, $3)",
            vec_str, limit, workspace_id,
        )
        for row in rows:
            results.append(SearchResult(
                source_table="projects",
                id=row["id"],
                primary_text=f"{row['name']}: {row['description'] or ''}",
                topics=list(row["topics"] or []),
                created_at=row["updated_at"],
                similarity=row["similarity"],
                metadata={"status": row["status"]},
            ))

    elif table == "ideas":
        rows = await conn.fetch(
            "SELECT * FROM match_ideas($1::vector, $2, $3, $4)",
            vec_str, limit, topic_filter, workspace_id,
        )
        for row in rows:
            results.append(SearchResult(
                source_table="ideas",
                id=row["id"],
                primary_text=f"{row['title']}: {row['elaboration'] or ''}",
                topics=list(row["topics"] or []),
                created_at=row["created_at"],
                similarity=row["similarity"],
            ))

    elif table == "admin":
        rows = await conn.fetch(
            "SELECT * FROM match_admin($1::vector, $2, NULL, $3)",
            vec_str, limit, workspace_id,
        )
        for row in rows:
            results.append(SearchResult(
                source_table="admin",
                id=row["id"],
                primary_text=row["task"],
                topics=list(row["topics"] or []),
                created_at=row["created_at"],
                similarity=row["similarity"],
                metadata={
                    "status": row["status"],
                    "action_items": list(row["action_items"] or []),
                },
            ))

    return results


@router.get(
    "/thoughts",
    response_model=ThoughtsResponse,
    summary="Paginated audit log of all ingested content",
)
async def list_thoughts(
    limit:     int = Query(default=20, ge=1, le=100),
    offset:    int = Query(default=0, ge=0),
    source:    Optional[str] = Query(default=None),
    workspace: WorkspaceRecord = Depends(get_workspace),
) -> ThoughtsResponse:
    pool = await get_pool()

    base_where = "WHERE workspace_id = $3"
    params: list = [limit, offset, workspace.id]

    if source:
        base_where += " AND source = $4"
        params.append(source)

    async with pool.acquire() as conn:
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM thoughts {base_where}",
            *params[2:],  # skip limit/offset for count
        )
        rows = await conn.fetch(
            f"""
            SELECT id, content, content_type, topics, people, source,
                   routed_to, confidence, created_at
            FROM thoughts
            {base_where}
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            *params,
        )

    items = [
        ThoughtItem(
            id=row["id"],
            content=row["content"],
            content_type=row["content_type"],
            topics=list(row["topics"] or []),
            people=list(row["people"] or []),
            source=row["source"],
            routed_to=row["routed_to"],
            confidence=row["confidence"] or 0.0,
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return ThoughtsResponse(
        items=items,
        total=count_row["total"],
        limit=limit,
        offset=offset,
    )
