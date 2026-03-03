"""
AxiomBrain — Graph Relationships (Neo4j backend)

All relationship edges are stored in Neo4j.
Postgres is still used for embedding-based project matching (fallback only).

Node model in Neo4j:
    (:Memory {id, table, display_name, topics, created_at})

Relationship types (lowercase to match existing API contract):
    works_on      person  → project
    belongs_to    idea    → project
    recorded_in   thought → project
    originated    person  → idea
    related_to    generic / manual

Public API is identical to the previous Postgres version — router.py and
all callers require no changes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from axiom_brain.database.neo4j import get_driver

logger = logging.getLogger(__name__)

_REL_TYPES = frozenset({
    "works_on", "belongs_to", "recorded_in", "originated", "related_to",
})
_VALID_TABLES = frozenset({"thoughts", "people", "projects", "ideas", "admin"})

# Map API table names to human-friendly display labels in Neo4j
_TABLE_DISPLAY = {
    "thoughts": "Thought",
    "people":   "Person",
    "projects": "Project",
    "ideas":    "Idea",
    "admin":    "Task",
}

# Cypher requires static relationship type identifiers — we whitelist and
# interpolate safely (never from user input without validation).
_VALID_REL_CYPHER = frozenset({
    "WORKS_ON", "BELONGS_TO", "RECORDED_IN", "ORIGINATED", "RELATED_TO",
})


def _to_cypher_rel(rel_type: str) -> str:
    """Convert lowercase API rel_type to uppercase Cypher relationship type."""
    upper = rel_type.upper()
    if upper not in _VALID_REL_CYPHER:
        raise ValueError(f"Invalid rel_type: {rel_type!r}")
    return upper


def _from_cypher_rel(rel_type: str) -> str:
    """Convert uppercase Cypher rel_type back to lowercase API form."""
    return rel_type.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Node upsert — called on every ingest to keep Neo4j in sync
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_node(
    table:        str,
    node_id:      UUID,
    display_name: str,
    topics:       Optional[List[str]] = None,
) -> None:
    """
    Create-or-update a Memory node in Neo4j.
    Safe to call repeatedly — uses MERGE on the unique id property.
    """
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            """
            MERGE (n:Memory {id: $id})
            ON CREATE SET
                n.table        = $table,
                n.display_name = $display_name,
                n.topics       = $topics,
                n.created_at   = $created_at
            ON MATCH SET
                n.display_name = $display_name,
                n.topics       = $topics
            """,
            id           = str(node_id),
            table        = table,
            display_name = display_name,
            topics       = topics or [],
            created_at   = datetime.now(timezone.utc).isoformat(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Core edge operations
# ─────────────────────────────────────────────────────────────────────────────

async def create_edge(
    conn,                          # asyncpg conn — kept for API compat, unused
    from_table:    str,
    from_id:       UUID,
    to_table:      str,
    to_id:         UUID,
    rel_type:      str   = "related_to",
    strength:      float = 1.0,
    auto_detected: bool  = False,
    source:        Optional[str]          = None,
    metadata:      Optional[Dict[str, Any]] = None,
) -> Optional[UUID]:
    """
    Create a relationship edge in Neo4j.
    Returns the new edge UUID, or None if the edge already exists (idempotent).
    """
    if from_table not in _VALID_TABLES or to_table not in _VALID_TABLES:
        raise ValueError(f"Invalid table: {from_table!r} or {to_table!r}")
    if rel_type not in _REL_TYPES:
        raise ValueError(f"Unknown rel_type: {rel_type!r}")

    cypher_rel = _to_cypher_rel(rel_type)
    edge_id    = str(uuid.uuid4())

    driver = await get_driver()
    async with driver.session() as session:
        # Ensure both nodes exist before linking
        for (tbl, nid) in ((from_table, from_id), (to_table, to_id)):
            await session.run(
                "MERGE (n:Memory {id: $id}) ON CREATE SET n.table = $table",
                id=str(nid), table=tbl,
            )

        # Check for duplicate before creating
        existing = await session.run(
            f"""
            MATCH (a:Memory {{id: $from_id}})-[r:{cypher_rel}]->(b:Memory {{id: $to_id}})
            RETURN r.id AS id LIMIT 1
            """,
            from_id=str(from_id),
            to_id=str(to_id),
        )
        record = await existing.single()
        if record:
            logger.debug("Edge already exists: %s -[%s]-> %s", from_id, rel_type, to_id)
            return None

        # Create the edge
        await session.run(
            f"""
            MATCH (a:Memory {{id: $from_id}})
            MATCH (b:Memory {{id: $to_id}})
            CREATE (a)-[r:{cypher_rel} {{
                id:            $edge_id,
                strength:      $strength,
                auto_detected: $auto_detected,
                source:        $source,
                metadata:      $metadata,
                created_at:    $created_at
            }}]->(b)
            """,
            from_id       = str(from_id),
            to_id         = str(to_id),
            edge_id       = edge_id,
            strength      = strength,
            auto_detected = auto_detected,
            source        = source or "unknown",
            metadata      = str(metadata or {}),
            created_at    = datetime.now(timezone.utc).isoformat(),
        )

    logger.debug("Created edge %s: %s -[%s]-> %s", edge_id, from_id, rel_type, to_id)
    return UUID(edge_id)


async def get_edges(
    conn,                          # asyncpg conn — kept for API compat, unused
    table:     str,
    node_id:   UUID,
    direction: str           = "both",
    rel_type:  Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all edges connected to a node from Neo4j."""
    if direction == "from":
        pattern = "(n:Memory {id: $nid})-[r]->(other:Memory)"
    elif direction == "to":
        pattern = "(n:Memory {id: $nid})<-[r]-(other:Memory)"
    else:
        pattern = "(n:Memory {id: $nid})-[r]-(other:Memory)"

    rel_filter = f"AND type(r) = '{_to_cypher_rel(rel_type)}'" if rel_type else ""

    cypher = f"""
        MATCH {pattern}
        WHERE n.table = $table {rel_filter}
        RETURN
            r.id            AS id,
            n.id            AS from_id,
            n.table         AS from_table,
            other.id        AS to_id,
            other.table     AS to_table,
            type(r)         AS rel_type,
            r.strength      AS strength,
            r.auto_detected AS auto_detected,
            r.source        AS source,
            r.created_at    AS created_at,
            r.metadata      AS metadata
        ORDER BY r.created_at DESC
    """

    driver = await get_driver()
    async with driver.session() as session:
        result  = await session.run(cypher, nid=str(node_id), table=table)
        records = await result.data()

    edges = []
    for rec in records:
        # Normalise: for "both" direction the from/to may be flipped
        # We always return from_id=source, to_id=target regardless of traversal dir
        edges.append({
            "id":            UUID(rec["id"]) if rec["id"] else uuid.uuid4(),
            "from_table":    rec["from_table"],
            "from_id":       UUID(rec["from_id"]),
            "to_table":      rec["to_table"],
            "to_id":         UUID(rec["to_id"]),
            "rel_type":      _from_cypher_rel(rec["rel_type"]),
            "strength":      float(rec["strength"] or 1.0),
            "auto_detected": bool(rec["auto_detected"]),
            "source":        rec["source"],
            "created_at":    _parse_dt(rec["created_at"]),
            "metadata":      {},
        })
    return edges


async def delete_edge(conn, edge_id: UUID) -> bool:
    """Delete a relationship by its id property. Returns True if deleted."""
    driver = await get_driver()
    async with driver.session() as session:
        result  = await session.run(
            "MATCH ()-[r {id: $eid}]-() DELETE r RETURN count(r) AS deleted",
            eid=str(edge_id),
        )
        record = await result.single()
    return bool(record and record["deleted"] > 0)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-hop traversal  (new capability unlocked by Neo4j)
# ─────────────────────────────────────────────────────────────────────────────

async def traverse(
    table:    str,
    node_id:  UUID,
    hops:     int = 2,
    limit:    int = 50,
) -> List[Dict[str, Any]]:
    """
    Return all nodes reachable within `hops` relationship steps.

    Each result contains:
        path_nodes  — ordered list of {id, table, display_name}
        path_rels   — ordered list of {type, strength}
        depth       — number of hops from start node
    """
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH path = (start:Memory {id: $node_id, table: $table})-[*1..$hops]-(other:Memory)
            WHERE other.id <> $node_id
            RETURN
                [n IN nodes(path) | {id: n.id, table: n.table, name: n.display_name}] AS path_nodes,
                [r IN relationships(path) | {type: toLower(type(r)), strength: r.strength}] AS path_rels,
                length(path) AS depth
            ORDER BY depth
            LIMIT $limit
            """,
            node_id=str(node_id),
            table=table,
            hops=hops,
            limit=limit,
        )
        records = await result.data()

    return [
        {
            "path_nodes": rec["path_nodes"],
            "path_rels":  rec["path_rels"],
            "depth":      rec["depth"],
        }
        for rec in records
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Auto-detection — runs after every ingest (same signature as before)
# ─────────────────────────────────────────────────────────────────────────────

async def auto_detect_relationships(
    conn,                          # asyncpg conn — still used for embedding fallback
    thought_id:    UUID,
    routed_table:  str,
    routed_id:     Optional[UUID],
    people:        List[str],
    topics:        List[str],
    source:        str = "auto",
    embedding:     Optional[List[float]] = None,
) -> List[UUID]:
    """
    Auto-detect and create Neo4j edges after a successful ingest.
    Logic is identical to the previous Postgres version.
    """
    created_edges: List[UUID] = []

    # ── Step 1: resolve project match ────────────────────────────────────────
    project_id: Optional[UUID] = None

    if routed_table == "projects" and routed_id:
        project_id = routed_id
    else:
        project_id = await _find_matching_project(topics)
        if project_id is None and embedding:
            project_id = await _find_project_by_embedding(conn, embedding)

    # ── Step 2: thought → project (recorded_in) ──────────────────────────────
    if project_id and routed_table == "thoughts":
        eid = await create_edge(
            conn, "thoughts", thought_id, "projects", project_id,
            rel_type="recorded_in", auto_detected=True, source=source,
        )
        if eid:
            created_edges.append(eid)

    # ── Step 3: idea → project (belongs_to) ──────────────────────────────────
    if project_id and routed_table == "ideas" and routed_id:
        eid = await create_edge(
            conn, "ideas", routed_id, "projects", project_id,
            rel_type="belongs_to", auto_detected=True, source=source,
        )
        if eid:
            created_edges.append(eid)

    # ── Step 4: person → project / person → idea ─────────────────────────────
    if people:
        person_ids = await _find_matching_people(conn, people)

        for person_id in person_ids:
            if project_id:
                eid = await create_edge(
                    conn, "people", person_id, "projects", project_id,
                    rel_type="works_on", auto_detected=True, source=source,
                )
                if eid:
                    created_edges.append(eid)

            if routed_table == "ideas" and routed_id:
                eid = await create_edge(
                    conn, "people", person_id, "ideas", routed_id,
                    rel_type="originated", auto_detected=True, source=source,
                )
                if eid:
                    created_edges.append(eid)

    logger.info(
        "Auto-detected %d relationship(s) for thought %s",
        len(created_edges), thought_id,
    )
    return created_edges


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _find_matching_project(topics: List[str]) -> Optional[UUID]:
    """Find a project in Neo4j whose topics overlap with the given list."""
    if not topics:
        return None
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Memory {table: 'projects'})
            WHERE any(t IN p.topics WHERE t IN $topics)
            RETURN p.id AS id
            LIMIT 1
            """,
            topics=topics,
        )
        record = await result.single()
    return UUID(record["id"]) if record else None


async def _find_project_by_embedding(
    conn,
    embedding: List[float],
    threshold: float = 0.3,
) -> Optional[UUID]:
    """
    Semantic fallback — embeddings live in Postgres so we still query there.
    Forces sequential scan (IVFFlat unreliable on small tables).
    """
    vec_str = f"[{','.join(str(x) for x in embedding)}]"
    await conn.execute("SET enable_indexscan = off")
    try:
        rows = await conn.fetch(
            """
            SELECT id, 1 - (embedding <=> $1::vector) AS similarity
            FROM   projects
            WHERE  embedding IS NOT NULL
            ORDER  BY embedding <=> $1::vector
            LIMIT  1
            """,
            vec_str,
        )
    finally:
        await conn.execute("SET enable_indexscan = on")

    if rows and rows[0]["similarity"] >= threshold:
        return rows[0]["id"]
    return None


async def _find_matching_people(conn, names: List[str]) -> List[UUID]:
    """Find people by name — query Neo4j first, fall back to Postgres if empty."""
    if not names:
        return []

    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Memory {table: 'people'})
            WHERE any(name IN $names WHERE toLower(p.display_name) CONTAINS toLower(name))
            RETURN p.id AS id
            """,
            names=names,
        )
        records = await result.data()

    if records:
        return [UUID(r["id"]) for r in records]

    # Postgres fallback (node may not be in Neo4j yet)
    rows = await conn.fetch(
        """
        SELECT id FROM people
        WHERE LOWER(name) = ANY(SELECT LOWER(unnest($1::text[])))
        """,
        names,
    )
    return [r["id"] for r in rows]


def _parse_dt(value) -> datetime:
    """Parse ISO string or passthrough datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
