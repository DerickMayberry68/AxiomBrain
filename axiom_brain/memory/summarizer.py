"""
AxiomBrain — LLM Summarizer
Compresses memory content into higher-level summaries using gpt-4o-mini.

Three summary modes:
  daily_thoughts   — roll up the past N hours of thoughts into a concise digest
  project_rollup   — summarize all memories linked to a specific project
  person_profile   — summarize all context known about a specific person
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from axiom_brain.config import get_settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

_DAILY_PROMPT = """You are summarizing a consultant's working memory for the day.
Below are raw notes, decisions, and observations stored in their AI brain tool.
Produce a concise daily digest (3-7 bullet points) covering:
- Key decisions made
- Important context or observations
- People or projects mentioned
- Action items or follow-ups needed

Be specific and factual. Do not invent details not present in the source material.

SOURCE MEMORIES ({count} items, {start} to {end}):
{memories}

DAILY DIGEST:"""

_PROJECT_PROMPT = """You are summarizing the current state of a project based on stored memories.
Produce a concise project status summary (4-8 bullet points) covering:
- What the project is and its current status
- Key decisions and milestones recorded
- People involved
- Open questions or next steps

Be specific and factual. Do not invent details not present in the source material.

PROJECT: {name}
SOURCE MEMORIES ({count} items):
{memories}

PROJECT STATUS SUMMARY:"""

_PERSON_PROMPT = """You are summarizing what is known about a person from stored memories.
Produce a concise person profile (3-6 bullet points) covering:
- Who this person is and their role
- Projects or topics they are associated with
- Key interactions or notes
- Any relevant context for working with them

Be specific and factual. Do not invent details not present in the source material.

PERSON: {name}
SOURCE MEMORIES ({count} items):
{memories}

PERSON PROFILE:"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────────────────────────────────────

async def _call_llm(prompt: str) -> str:
    """Send prompt to gpt-4o-mini and return the completion text."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.classifier_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


# ─────────────────────────────────────────────────────────────────────────────
# Summary builders
# ─────────────────────────────────────────────────────────────────────────────

async def summarize_daily_thoughts(
    conn,
    hours_back: int = 24,
    min_count:  int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Summarize unsummarized thoughts from the last N hours.
    Returns a dict ready to insert into the summaries table, or None if
    there aren't enough new thoughts to warrant a summary.
    """
    rows = await conn.fetch(
        """
        SELECT id, content, content_type, topics, source, created_at
        FROM   thoughts
        WHERE  summarized_at IS NULL
          AND  created_at >= NOW() - ($1 || ' hours')::interval
        ORDER  BY created_at ASC
        """,
        str(hours_back),
    )

    if len(rows) < min_count:
        logger.info("daily_thoughts: only %d unsummarized thoughts, skipping", len(rows))
        return None

    thought_ids  = [r["id"] for r in rows]
    period_start = rows[0]["created_at"]
    period_end   = rows[-1]["created_at"]

    memory_text = "\n".join(
        f"[{r['created_at'].strftime('%Y-%m-%d %H:%M')} | {r['source'] or 'unknown'}] "
        f"{r['content']}"
        for r in rows
    )

    prompt  = _DAILY_PROMPT.format(
        count=len(rows),
        start=period_start.strftime("%Y-%m-%d %H:%M"),
        end=period_end.strftime("%Y-%m-%d %H:%M"),
        memories=memory_text,
    )
    summary = await _call_llm(prompt)

    # Collect topics from source memories
    all_topics: list[str] = []
    for r in rows:
        all_topics.extend(r["topics"] or [])
    unique_topics = list(dict.fromkeys(all_topics))[:10]

    return {
        "summary_type":  "daily_thoughts",
        "subject_table": None,
        "subject_id":    None,
        "subject_name":  f"Daily digest {period_end.strftime('%Y-%m-%d')}",
        "content":       summary,
        "source_count":  len(rows),
        "period_start":  period_start,
        "period_end":    period_end,
        "topics":        unique_topics,
        "thought_ids":   thought_ids,   # used to mark as summarized
    }


async def summarize_project(
    conn,
    project_id: UUID,
) -> Optional[Dict[str, Any]]:
    """
    Summarize all memories linked to a project via relationships.
    Returns a dict ready to insert into summaries, or None if no content found.
    """
    # Get project details
    project = await conn.fetchrow(
        "SELECT id, name, description, topics FROM projects WHERE id = $1",
        project_id,
    )
    if not project:
        return None

    # Get all thoughts linked to this project via relationships
    rows = await conn.fetch(
        """
        SELECT t.content, t.created_at, t.source, t.topics
        FROM   thoughts t
        JOIN   relationships r
               ON r.from_table = 'thoughts' AND r.from_id = t.id
               AND r.to_table = 'projects'  AND r.to_id   = $1
        UNION
        -- Also include direct thoughts that mentioned this project
        SELECT t.content, t.created_at, t.source, t.topics
        FROM   thoughts t
        WHERE  t.routed_to = 'projects'
          AND  EXISTS (
              SELECT 1 FROM projects p
              WHERE  p.id = $1
                AND  t.content ILIKE '%' || SPLIT_PART(p.name, ' ', 1) || '%'
          )
        ORDER  BY created_at ASC
        LIMIT  50
        """,
        project_id,
    )

    if not rows:
        logger.info("project_rollup: no memories found for project %s", project_id)
        return None

    memory_text = "\n".join(
        f"[{r['created_at'].strftime('%Y-%m-%d %H:%M')} | {r['source'] or 'unknown'}] "
        f"{r['content']}"
        for r in rows
    )
    if project["description"] and project["description"] != project["name"]:
        memory_text = f"Project description: {project['description']}\n\n" + memory_text

    prompt  = _PROJECT_PROMPT.format(
        name=project["name"],
        count=len(rows),
        memories=memory_text,
    )
    summary = await _call_llm(prompt)

    period_start = rows[0]["created_at"]  if rows else None
    period_end   = rows[-1]["created_at"] if rows else None

    return {
        "summary_type":  "project_rollup",
        "subject_table": "projects",
        "subject_id":    project_id,
        "subject_name":  project["name"],
        "content":       summary,
        "source_count":  len(rows),
        "period_start":  period_start,
        "period_end":    period_end,
        "topics":        list(project["topics"] or []),
        "thought_ids":   [],
    }


async def summarize_person(
    conn,
    person_id: UUID,
) -> Optional[Dict[str, Any]]:
    """
    Summarize all known context about a person.
    Returns a dict ready to insert into summaries, or None if no content found.
    """
    person = await conn.fetchrow(
        "SELECT id, name, notes, topics FROM people WHERE id = $1",
        person_id,
    )
    if not person:
        return None

    # Thoughts that mention this person by name
    rows = await conn.fetch(
        """
        SELECT content, created_at, source, topics
        FROM   thoughts
        WHERE  $1 = ANY(people)
           OR  content ILIKE '%' || $2 || '%'
        ORDER  BY created_at ASC
        LIMIT  30
        """,
        person["name"], person["name"],
    )

    if not rows:
        logger.info("person_profile: no memories found for person %s", person_id)
        return None

    memory_text = "\n".join(
        f"[{r['created_at'].strftime('%Y-%m-%d %H:%M')} | {r['source'] or 'unknown'}] "
        f"{r['content']}"
        for r in rows
    )
    if person["notes"]:
        memory_text = f"Existing notes: {person['notes']}\n\n" + memory_text

    prompt  = _PERSON_PROMPT.format(
        name=person["name"],
        count=len(rows),
        memories=memory_text,
    )
    summary = await _call_llm(prompt)

    period_start = rows[0]["created_at"]  if rows else None
    period_end   = rows[-1]["created_at"] if rows else None

    all_topics: list[str] = list(person["topics"] or [])
    for r in rows:
        all_topics.extend(r["topics"] or [])
    unique_topics = list(dict.fromkeys(all_topics))[:10]

    return {
        "summary_type":  "person_profile",
        "subject_table": "people",
        "subject_id":    person_id,
        "subject_name":  person["name"],
        "content":       summary,
        "source_count":  len(rows),
        "period_start":  period_start,
        "period_end":    period_end,
        "topics":        unique_topics,
        "thought_ids":   [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persist summary to DB
# ─────────────────────────────────────────────────────────────────────────────

async def save_summary(conn, result: Dict[str, Any], embedder) -> UUID:
    """
    Embed and persist a summary dict to the summaries table.
    Marks source thoughts as summarized if thought_ids are provided.
    """
    embedding = await embedder.embed(result["content"])
    vec_str   = f"[{','.join(str(x) for x in embedding)}]"

    row = await conn.fetchrow(
        """
        INSERT INTO summaries
            (summary_type, subject_table, subject_id, subject_name,
             content, embedding, source_count,
             period_start, period_end, topics)
        VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8, $9, $10::text[])
        RETURNING id
        """,
        result["summary_type"],
        result["subject_table"],
        result["subject_id"],
        result["subject_name"],
        result["content"],
        vec_str,
        result["source_count"],
        result["period_start"],
        result["period_end"],
        result["topics"],
    )
    summary_id = row["id"]

    # Mark thoughts as summarized
    thought_ids = result.get("thought_ids") or []
    if thought_ids:
        await conn.execute(
            "UPDATE thoughts SET summarized_at = NOW() WHERE id = ANY($1::uuid[])",
            thought_ids,
        )
        logger.info("Marked %d thoughts as summarized", len(thought_ids))

    return summary_id
