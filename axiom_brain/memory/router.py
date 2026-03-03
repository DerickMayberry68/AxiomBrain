"""
AxiomBrain — Router
Orchestrates the full ingest pipeline: embed → classify → route.
Routes content to the correct table based on classification confidence.
Always writes to 'thoughts' as an immutable audit trail.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from axiom_brain.config import get_settings
from axiom_brain.database.connection import get_pool
from axiom_brain.memory.classifier import ClassificationResult, ContentType, get_classifier
from axiom_brain.memory.embedder import get_embedder
from axiom_brain.memory.graph import auto_detect_relationships


# Map content type → target table name
_TYPE_TO_TABLE: dict[ContentType, str] = {
    ContentType.OBSERVATION: "thoughts",
    ContentType.TASK:        "admin",
    ContentType.IDEA:        "ideas",
    ContentType.REFERENCE:   "projects",
    ContentType.PERSON_NOTE: "people",
}


@dataclass
class IngestResult:
    thought_id:    UUID
    routed_to:     str          # actual table written to (may differ from classification if confidence low)
    routed_id:     Optional[UUID]
    content_type:  str
    confidence:    float
    topics:        List[str]
    people:        List[str]
    action_items:  List[str]


class MemoryRouter:
    """Runs the full embed → classify → route pipeline for a single content item."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def ingest(
        self,
        content: str,
        source: str = "unknown",
        target_table: Optional[str] = None,  # Override routing if caller knows the type
    ) -> IngestResult:
        """
        Full pipeline:
        1. Embed content
        2. Classify content
        3. Write to thoughts (always)
        4. Write to target table (if routed away from thoughts)
        Returns an IngestResult with IDs and metadata.
        """
        embedder   = get_embedder()
        classifier = get_classifier()
        pool       = await get_pool()

        # Step 1 & 2 — run embedding and classification concurrently
        embedding, classification = await asyncio.gather(
            embedder.embed(content),
            classifier.classify(content),
        )

        # Step 3 — determine target table
        routed_table = _resolve_target_table(
            classification=classification,
            threshold=self._settings.confidence_threshold,
            override=target_table,
        )

        # Step 4 — write to DB
        async with pool.acquire() as conn:
            thought_id = await _write_thought(
                conn=conn,
                content=content,
                embedding=embedding,
                classification=classification,
                source=source,
                routed_to=routed_table,
            )

            routed_id: Optional[UUID] = None
            if routed_table != "thoughts":
                routed_id = await _write_to_table(
                    conn=conn,
                    table=routed_table,
                    content=content,
                    embedding=embedding,
                    classification=classification,
                )

            # Step 5 — auto-detect graph relationships
            await auto_detect_relationships(
                conn=conn,
                thought_id=thought_id,
                routed_table=routed_table,
                routed_id=routed_id,
                people=classification.people,
                topics=classification.topics,
                source=source,
                embedding=embedding,
            )

        return IngestResult(
            thought_id=thought_id,
            routed_to=routed_table,
            routed_id=routed_id,
            content_type=classification.content_type.value,
            confidence=classification.confidence,
            topics=classification.topics,
            people=classification.people,
            action_items=classification.action_items,
        )


def _resolve_target_table(
    classification: ClassificationResult,
    threshold: float,
    override: Optional[str],
) -> str:
    if override and override in ("thoughts", "people", "projects", "ideas", "admin"):
        return override
    if classification.confidence >= threshold:
        return _TYPE_TO_TABLE[classification.content_type]
    return "thoughts"   # Default fallback


async def _write_thought(
    conn,
    content: str,
    embedding: List[float],
    classification: ClassificationResult,
    source: str,
    routed_to: str,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO thoughts
            (content, embedding, content_type, topics, people, action_items,
             confidence, source, routed_to)
        VALUES ($1, $2::vector, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        content,
        f"[{','.join(str(x) for x in embedding)}]",
        classification.content_type.value,
        classification.topics,
        classification.people,
        classification.action_items,
        classification.confidence,
        source,
        routed_to,
    )
    return row["id"]


async def _write_to_table(
    conn,
    table: str,
    content: str,
    embedding: List[float],
    classification: ClassificationResult,
) -> Optional[UUID]:
    """Write to the appropriate secondary table based on routing decision."""
    vec_str = f"[{','.join(str(x) for x in embedding)}]"

    if table == "people":
        row = await conn.fetchrow(
            """
            INSERT INTO people (name, notes, embedding, topics, last_seen)
            VALUES (
                COALESCE(($2::text[])[1], 'Unknown'),
                $1, $3::vector, $4::text[], NOW()
            )
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            content,
            classification.people or ["Unknown"],
            vec_str,
            classification.topics,
        )

    elif table == "ideas":
        # Use first 120 chars as title, rest as elaboration
        title = content[:120].rstrip()
        elaboration = content[120:] if len(content) > 120 else None
        row = await conn.fetchrow(
            """
            INSERT INTO ideas (title, elaboration, embedding, topics)
            VALUES ($1, $2, $3::vector, $4::text[])
            RETURNING id
            """,
            title, elaboration, vec_str, classification.topics,
        )

    elif table == "admin":
        row = await conn.fetchrow(
            """
            INSERT INTO admin (task, embedding, action_items, topics)
            VALUES ($1, $2::vector, $3::text[], $4::text[])
            RETURNING id
            """,
            content, vec_str, classification.action_items, classification.topics,
        )

    elif table == "projects":
        row = await conn.fetchrow(
            """
            INSERT INTO projects (name, description, embedding, topics)
            VALUES ($1, $1, $2::vector, $3::text[])
            RETURNING id
            """,
            content[:200], vec_str, classification.topics,
        )

    else:
        return None

    return row["id"] if row else None


# Module-level singleton
_router: MemoryRouter | None = None


def get_router() -> MemoryRouter:
    global _router
    if _router is None:
        _router = MemoryRouter()
    return _router
