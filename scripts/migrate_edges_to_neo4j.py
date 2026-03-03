"""
AxiomBrain — One-time migration: Postgres relationships → Neo4j

Reads every row from the Postgres `relationships` table and creates the
corresponding Memory nodes + edges in Neo4j.

Also seeds Memory nodes for all existing rows in the five content tables
so the graph is fully populated from the start.

Run once:
    python scripts/migrate_edges_to_neo4j.py

Safe to re-run — all Cypher operations use MERGE (idempotent).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make sure the project root is on PYTHONPATH when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from neo4j import AsyncGraphDatabase

from axiom_brain.config import get_settings


async def main() -> None:
    settings = get_settings()
    print(f"Connecting to Postgres: {settings.database_url[:40]}...")
    print(f"Connecting to Neo4j:    {settings.neo4j_uri}")

    pg   = await asyncpg.connect(dsn=settings.database_url)
    neo4j = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    try:
        async with neo4j.session() as session:

            # ── 1. Ensure schema ─────────────────────────────────────────────
            await session.run(
                "CREATE CONSTRAINT memory_id_unique IF NOT EXISTS "
                "FOR (n:Memory) REQUIRE n.id IS UNIQUE"
            )
            await session.run(
                "CREATE INDEX memory_table_idx IF NOT EXISTS "
                "FOR (n:Memory) ON (n.table)"
            )
            print("Neo4j schema verified.")

            # ── 2. Seed Memory nodes from all five Postgres tables ───────────
            node_map = {
                "thoughts": ("content",     "content"),
                "people":   ("name",        "name"),
                "projects": ("name",        "name"),
                "ideas":    ("title",       "title"),
                "admin":    ("task",        "task"),
            }

            total_nodes = 0
            for table, (col, _) in node_map.items():
                rows = await pg.fetch(
                    f"SELECT id, {col} AS display_name, topics, created_at FROM {table}"
                )
                for row in rows:
                    display = (str(row["display_name"] or ""))[:120]
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
                        id           = str(row["id"]),
                        table        = table,
                        display_name = display,
                        topics       = list(row["topics"] or []),
                        created_at   = row["created_at"].isoformat() if row["created_at"] else "",
                    )
                    total_nodes += 1

                print(f"  {table:<12} — {len(rows)} nodes seeded")

            print(f"Total Memory nodes seeded: {total_nodes}")

            # ── 3. Migrate relationship edges ────────────────────────────────
            edges = await pg.fetch("SELECT * FROM relationships ORDER BY created_at")
            print(f"\nMigrating {len(edges)} relationship edges...")

            _REL_MAP = {
                "works_on":    "WORKS_ON",
                "belongs_to":  "BELONGS_TO",
                "recorded_in": "RECORDED_IN",
                "originated":  "ORIGINATED",
                "related_to":  "RELATED_TO",
            }

            skipped = 0
            migrated = 0
            for edge in edges:
                cypher_rel = _REL_MAP.get(edge["rel_type"])
                if not cypher_rel:
                    print(f"  SKIP unknown rel_type: {edge['rel_type']}")
                    skipped += 1
                    continue

                await session.run(
                    f"""
                    MERGE (a:Memory {{id: $from_id}})
                      ON CREATE SET a.table = $from_table
                    MERGE (b:Memory {{id: $to_id}})
                      ON CREATE SET b.table = $to_table
                    MERGE (a)-[r:{cypher_rel} {{id: $edge_id}}]->(b)
                      ON CREATE SET
                        r.strength      = $strength,
                        r.auto_detected = $auto_detected,
                        r.source        = $source,
                        r.created_at    = $created_at,
                        r.metadata      = $metadata
                    """,
                    from_id       = str(edge["from_id"]),
                    from_table    = edge["from_table"],
                    to_id         = str(edge["to_id"]),
                    to_table      = edge["to_table"],
                    edge_id       = str(edge["id"]),
                    strength      = float(edge["strength"] or 1.0),
                    auto_detected = bool(edge["auto_detected"]),
                    source        = edge["source"] or "migrated",
                    created_at    = edge["created_at"].isoformat() if edge["created_at"] else "",
                    metadata      = str(edge["metadata"] or "{}"),
                )
                migrated += 1

            print(f"Edges migrated: {migrated}  |  skipped: {skipped}")

    finally:
        await pg.close()
        await neo4j.close()

    print("\nMigration complete.")
    print("You can verify in Neo4j Browser:")
    print("  MATCH (n:Memory) RETURN count(n)")
    print("  MATCH ()-[r]->() RETURN count(r)")


if __name__ == "__main__":
    asyncio.run(main())
