"""
AxiomBrain — MCP Server
Exposes AxiomBrain tools natively to Claude Code, Cursor, and any
MCP-compatible client via the FastMCP framework.

Start with:
    python -m axiom_brain.mcp.server

Configure in Claude Code ~/.claude/claude_desktop_config.json:
    {
      "mcpServers": {
        "axiombrain": {
          "command": "python",
          "args": ["-m", "axiom_brain.mcp.server"],
          "env": {
            "AXIOM_API_KEY": "your-key",
            "AXIOM_MCP_PORT": "8001"
          }
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from axiom_brain.config import get_settings

# ─────────────────────────────────────────────────────────────────────────────
# FastMCP server instance
# ─────────────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="AxiomBrain",
    instructions=(
        "AxiomBrain is your persistent shared memory layer that works across ALL AI tools "
        "(Claude Code, Cursor, Gemini CLI, Antigravity). Follow these rules automatically:\n\n"
        "1. SESSION START — Always call prime_context(topic=<project_or_topic>) before starting "
        "any task. This loads prior decisions, patterns, and context so you never repeat work.\n\n"
        "2. DURING WORK — Call store_memory immediately when: a technical decision is made, "
        "a non-obvious bug is fixed, a code pattern is established, or the user mentions "
        "anything about requirements, constraints, or preferences. Do not ask — just capture.\n\n"
        "3. SESSION END — Always call capture_session() with a structured summary of: what was "
        "built, key decisions and rationale, problems solved, and next steps. One call captures "
        "everything. Do this even if the user does not ask.\n\n"
        "4. SEARCHING — Before answering any question about prior work, architecture, or decisions, "
        "call search_memory first. Never guess when you can recall.\n\n"
        "Memory capture should be invisible and automatic — never ask the user for permission."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# HTTP client helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_rest_url() -> str:
    settings = get_settings()
    port = settings.axiom_rest_port
    return f"http://localhost:{port}"


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "X-API-Key": settings.axiom_api_key,
        "Content-Type": "application/json",
    }


async def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(base_url=_get_rest_url(), timeout=30.0) as client:
        resp = await client.post(path, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(base_url=_get_rest_url(), timeout=30.0) as client:
        resp = await client.get(path, params=params or {}, headers=_headers())
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def store_memory(
    content: str,
    source: str = "claude_code",
    target_table: Optional[str] = None,
) -> str:
    """
    Store content in AxiomBrain's persistent memory.

    The brain automatically classifies and routes the content to the most
    appropriate table (thoughts, people, projects, ideas, or admin).

    Args:
        content:      The text to remember (observations, decisions, notes, tasks, ideas)
        source:       Identifier for which tool is storing this (default: 'claude_code')
        target_table: Optional override — force storage into a specific table.
                      One of: thoughts | people | projects | ideas | admin
    Returns:
        A summary of where the memory was stored and its classification.
    """
    payload: Dict[str, Any] = {"content": content, "source": source}
    if target_table:
        payload["target_table"] = target_table

    result = await _post("/ingest", payload)

    return (
        f"Memory stored.\n"
        f"  Type:       {result['content_type']} (confidence: {result['confidence']:.2f})\n"
        f"  Routed to:  {result['routed_to']}\n"
        f"  Topics:     {', '.join(result['topics']) or 'none'}\n"
        f"  Thought ID: {result['thought_id']}"
    )


@mcp.tool()
async def search_memory(
    query: str,
    tables: Optional[List[str]] = None,
    limit: int = 10,
) -> str:
    """
    Search AxiomBrain's memory using semantic similarity.

    Embeds the query and finds the most relevant stored memories across
    all tables (or a specified subset).

    Args:
        query:  Natural language search query
        tables: Optional list of tables to search. Defaults to all tables.
                Valid values: thoughts | people | projects | ideas | admin
        limit:  Maximum number of results to return (default 10, max 50)
    Returns:
        Ranked list of matching memories with similarity scores.
    """
    payload: Dict[str, Any] = {"query": query, "limit": limit}
    if tables:
        payload["tables"] = tables

    result = await _post("/search", payload)

    if not result["results"]:
        return f"No memories found matching: '{query}'"

    lines = [f"Found {result['count']} memories for: '{query}'\n"]
    for i, r in enumerate(result["results"], 1):
        similarity_pct = int(r["similarity"] * 100)
        lines.append(
            f"{i}. [{r['source_table'].upper()}] ({similarity_pct}% match)\n"
            f"   {r['primary_text'][:200]}"
            + ("..." if len(r["primary_text"]) > 200 else "")
        )
        if r.get("topics"):
            lines.append(f"   Topics: {', '.join(r['topics'])}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_context(
    topic: str,
    limit: int = 5,
) -> str:
    """
    Retrieve recent context related to a specific topic or person.

    Useful for priming a conversation with relevant background before
    starting work on a task.

    Args:
        topic:  Topic keyword or person name to search for
        limit:  Number of memories to return (default 5)
    Returns:
        Relevant context from across all memory tables.
    """
    payload = {"query": topic, "limit": limit, "topic_filter": topic}
    result  = await _post("/search", payload)

    if not result["results"]:
        return f"No context found for topic: '{topic}'"

    lines = [f"Context for '{topic}':\n"]
    for r in result["results"]:
        lines.append(f"[{r['source_table'].upper()}] {r['primary_text'][:300]}\n")

    return "\n".join(lines)


@mcp.tool()
async def list_projects(status: str = "active") -> str:
    """
    List projects stored in the brain.

    Args:
        status: Filter by status — 'active' | 'paused' | 'completed' (default: 'active')
    Returns:
        List of projects with descriptions.
    """
    result = await _get("/search", {
        "query": "project",
        "tables": ["projects"],
        "limit": 20,
    })

    # Actually call search with a broad query against the projects table
    payload = {"query": "project status goals", "tables": ["projects"], "limit": 20}
    result  = await _post("/search", payload)

    if not result["results"]:
        return "No projects found in the brain."

    lines = ["Projects:\n"]
    for r in result["results"]:
        meta   = r.get("metadata", {})
        pstatus = meta.get("status", "unknown") if meta else "unknown"
        if status and pstatus != status:
            continue
        lines.append(f"• {r['primary_text'][:200]}  [{pstatus}]")

    return "\n".join(lines) if len(lines) > 1 else f"No {status} projects found."


@mcp.tool()
async def add_task(
    task: str,
    due_date: Optional[str] = None,
) -> str:
    """
    Add a task directly to the admin (task management) table.

    Args:
        task:     Task description
        due_date: Optional ISO 8601 due date (e.g. '2026-03-15T09:00:00')
    Returns:
        Confirmation with the stored task ID.
    """
    content = task
    if due_date:
        content += f" [due: {due_date}]"

    payload = {
        "content": content,
        "source": "mcp_add_task",
        "target_table": "admin",
    }
    result = await _post("/ingest", payload)
    return f"Task stored in admin table.\n  ID: {result['thought_id']}\n  Task: {task}"


@mcp.tool()
async def brain_stats() -> str:
    """
    Return memory statistics — row counts and last-update timestamps for all tables.

    Returns:
        A summary table showing how much is stored in each memory table.
    """
    result = await _get("/stats")

    lines = ["AxiomBrain Memory Stats:\n"]
    for t in result["tables"]:
        last = t["last_update"] or "never"
        if isinstance(last, str) and len(last) > 19:
            last = last[:19]
        lines.append(f"  {t['table']:<12} {t['row_count']:>6} records   last: {last}")

    lines.append(f"\n  DB status: {'OK' if result['db_ok'] else 'ERROR'}")
    return "\n".join(lines)


@mcp.tool()
async def link_memories(
    from_table: str,
    from_id:    str,
    to_table:   str,
    to_id:      str,
    rel_type:   str   = "related_to",
    strength:   float = 1.0,
) -> str:
    """
    Manually create a relationship edge between two memory nodes.

    Use this when you know two pieces of information are connected and want
    to make that relationship explicit in the brain.

    Args:
        from_table: Source table — thoughts | people | projects | ideas | admin
        from_id:    UUID of the source node
        to_table:   Target table — thoughts | people | projects | ideas | admin
        to_id:      UUID of the target node
        rel_type:   Relationship type:
                      works_on    — person → project
                      belongs_to  — idea → project
                      recorded_in — thought → project
                      originated  — person → idea
                      related_to  — generic link (default)
        strength:   Edge weight 0.0–1.0 (default 1.0)
    Returns:
        Confirmation with the new edge ID.
    """
    payload: Dict[str, Any] = {
        "from_table": from_table,
        "from_id":    from_id,
        "to_table":   to_table,
        "to_id":      to_id,
        "rel_type":   rel_type,
        "strength":   strength,
        "source":     "mcp_manual",
    }
    try:
        result = await _post("/relationships", payload)
        return (
            f"Relationship created.\n"
            f"  Edge ID:  {result['id']}\n"
            f"  {from_table}/{from_id[:8]}... —[{rel_type}]→ {to_table}/{to_id[:8]}...\n"
            f"  Strength: {strength}"
        )
    except Exception as exc:
        return f"Failed to create relationship: {exc}"


@mcp.tool()
async def summarize_memories(
    hours_back:        int = 24,
    min_thought_count: int = 3,
) -> str:
    """
    Trigger the AxiomBrain summarization pipeline on-demand.

    Compresses recent thoughts into a daily digest, re-summarizes active
    projects, and updates person profiles.  Safe to call at any time —
    thoughts are only consumed into a summary once.

    Args:
        hours_back:        How many hours of unsummarized thoughts to include
                           in the daily digest (default 24, max 168 / 1 week)
        min_thought_count: Minimum number of thoughts required to produce a
                           daily digest — avoids trivial summaries (default 3)
    Returns:
        A brief report of what was created.
    """
    payload: Dict[str, Any] = {
        "hours_back":        hours_back,
        "min_thought_count": min_thought_count,
    }
    try:
        result = await _post("/summarize", payload)
        lines = ["Summarization complete.\n"]
        lines.append(f"  Daily digest:  {'created' if result['daily_created'] else 'skipped (not enough new thoughts)'}")
        lines.append(f"  Projects:      {result['projects_summarized']} summarized")
        lines.append(f"  People:        {result['people_summarized']} summarized")
        if result["summary_ids"]:
            lines.append(f"  Summary IDs:   {len(result['summary_ids'])} new summary record(s)")
        if result["errors"]:
            lines.append(f"  Errors:        {len(result['errors'])} (check server logs)")
        return "\n".join(lines)
    except Exception as exc:
        return f"Summarization failed: {exc}"


@mcp.tool()
async def get_summaries(
    summary_type: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    Retrieve recent summaries from AxiomBrain.

    Use this to quickly recall high-level digests without sifting through
    individual memories.

    Args:
        summary_type: Filter by type:
                        daily_thoughts  — daily thought digests
                        project_rollup  — project status summaries
                        person_profile  — person context profiles
                      Omit to return all types.
        limit:        Maximum summaries to return (default 10, max 100)
    Returns:
        Formatted list of summaries.
    """
    params: Dict[str, Any] = {"limit": limit}
    if summary_type:
        params["summary_type"] = summary_type

    result = await _get("/summaries", params)

    if not result["items"]:
        return "No summaries found."

    lines = [f"Found {result['total']} summary record(s) — showing {len(result['items'])}:\n"]
    for s in result["items"]:
        date_label = (s.get("period_end") or s.get("created_at") or "")[:10]
        lines.append(
            f"[{s['summary_type'].upper()}] {s.get('subject_name', '—')}  ({date_label})\n"
            f"  {s['content'][:400]}" + ("..." if len(s["content"]) > 400 else "")
        )
        if s.get("topics"):
            lines.append(f"  Topics: {', '.join(s['topics'][:5])}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_relationships(
    table:     str,
    node_id:   str,
    direction: str           = "both",
    rel_type:  Optional[str] = None,
) -> str:
    """
    Retrieve all relationship edges connected to a memory node.

    Use this to explore how a person, project, idea, or thought is connected
    to other items in the brain.

    Args:
        table:     The table the node lives in — thoughts | people | projects | ideas | admin
        node_id:   UUID of the node to inspect
        direction: 'from' (outgoing), 'to' (incoming), or 'both' (default)
        rel_type:  Optional filter — only return edges of this type
    Returns:
        List of connected nodes with relationship types and strengths.
    """
    params: Dict[str, Any] = {"direction": direction}
    if rel_type:
        params["rel_type"] = rel_type

    result = await _get(f"/relationships/{table}/{node_id}", params)

    if result["count"] == 0:
        return f"No relationships found for {table}/{node_id}"

    lines = [f"{result['count']} relationship(s) for {table}/{node_id[:8]}...:\n"]
    for r in result["relationships"]:
        tag = "auto" if r["auto_detected"] else "manual"
        lines.append(
            f"  [{r['rel_type']}] ({tag}, strength {r['strength']:.1f})\n"
            f"    {r['from_table']}/{str(r['from_id'])[:8]}... "
            f"→ {r['to_table']}/{str(r['to_id'])[:8]}..."
        )
    return "\n".join(lines)



@mcp.tool()
async def recalculate_decay() -> str:
    """
    Trigger an immediate recalculation of decay scores across all memory tables.

    Normally runs automatically at 2:30 AM.  Call this after a burst of new
    memories to ensure search rankings reflect current freshness.

    Returns:
        Row counts per table confirming the update completed.
    """
    try:
        result = await _post("/decay/recalculate", {})
        lines = ["Decay scores recalculated.\n"]
        if result.get("counts"):
            for table, count in result["counts"].items():
                lines.append(f"  {table:<12} {count:>6} rows updated")
        return "\n".join(lines)
    except Exception as exc:
        return f"Decay recalculation failed: {exc}"



@mcp.tool()
async def prime_context(
    topic:   str,
    limit:   int = 8,
) -> str:
    """
    Load relevant context from AxiomBrain at the START of a session.

    Call this AUTOMATICALLY at the beginning of every task or conversation
    to prime yourself with what has been worked on before.  Returns a
    formatted briefing of memories, summaries, and graph connections.

    Args:
        topic:  Project name, technology, or topic you are about to work on
        limit:  Number of memories to retrieve (default 8)
    Returns:
        A structured context briefing ready to inform your responses.
    """
    # Search for relevant memories
    payload = {"query": topic, "limit": limit}
    memories = await _post("/search", payload)

    # Pull most recent summaries related to the topic
    summaries = await _get("/summaries", {"limit": 5})

    lines = [f"Context briefing for: '{topic}'\n"]
    lines.append("=" * 50)

    if memories.get("results"):
        lines.append(f"\n{len(memories['results'])} relevant memories:\n")
        for i, r in enumerate(memories["results"], 1):
            pct = int(r["similarity"] * 100)
            lines.append(
                f"{i}. [{r['source_table'].upper()}] ({pct}% match)\n"
                f"   {r['primary_text'][:300]}"
                + ("..." if len(r["primary_text"]) > 300 else "")
            )
            lines.append("")
    else:
        lines.append("No prior memories found for this topic.")

    if summaries.get("items"):
        recent = summaries["items"][:3]
        lines.append(f"\nRecent summaries ({len(recent)}):\n")
        for s in recent:
            date = (s.get("created_at") or "")[:10]
            lines.append(
                f"[{s['summary_type'].upper()}] {s.get('subject_name', '—')} ({date})\n"
                f"  {s['content'][:300]}"
                + ("..." if len(s["content"]) > 300 else "")
            )
            lines.append("")

    lines.append("=" * 50)
    lines.append("Context loaded. Proceed with full awareness of prior work.")
    return "\n".join(lines)


@mcp.tool()
async def capture_session(
    summary:         str,
    decisions:       str = "",
    problems_solved: str = "",
    next_steps:      str = "",
    project:         str = "",
    source:          str = "claude_code",
) -> str:
    """
    Capture a complete work session into AxiomBrain in one call.

    Call this AUTOMATICALLY at the end of every task, feature, or
    significant chunk of work.  Stores the session across multiple
    memory types for rich future recall.

    Args:
        summary:         What was accomplished in this session (required)
        decisions:       Key technical or product decisions made, and why
        problems_solved: Issues encountered and how they were resolved
        next_steps:      Remaining TODOs or open questions for next session
        project:         Project name for context (auto-detected if blank)
        source:          Which AI tool is capturing (claude_code, cursor, gemini, etc.)
    Returns:
        Confirmation of what was stored.
    """
    stored: list[str] = []
    errors: list[str] = []

    async def ingest(content: str, target: Optional[str] = None) -> Optional[str]:
        payload: Dict[str, Any] = {"content": content, "source": source}
        if target:
            payload["target_table"] = target
        try:
            r = await _post("/ingest", payload)
            return r.get("thought_id")
        except Exception as exc:
            errors.append(str(exc))
            return None

    # 1. Session summary → let router classify (usually thoughts or projects)
    prefix = f"[Session summary — {project}] " if project else "[Session summary] "
    tid = await ingest(prefix + summary)
    if tid:
        stored.append(f"summary → {tid[:8]}...")

    # 2. Decisions → thoughts table (important for future context)
    if decisions.strip():
        tid = await ingest(
            f"[Decision] {project + ': ' if project else ''}{decisions}"
        )
        if tid:
            stored.append(f"decisions → {tid[:8]}...")

    # 3. Problems solved → thoughts (searchable by problem keywords)
    if problems_solved.strip():
        tid = await ingest(
            f"[Problem solved] {project + ': ' if project else ''}{problems_solved}"
        )
        if tid:
            stored.append(f"problems → {tid[:8]}...")

    # 4. Next steps → admin table (shows up as tasks)
    if next_steps.strip():
        tid = await ingest(
            f"[Next steps — {project}] {next_steps}" if project else f"[Next steps] {next_steps}",
            target="admin",
        )
        if tid:
            stored.append(f"next_steps → {tid[:8]}...")

    result = [f"Session captured ({len(stored)} memories stored)."]
    if stored:
        result.append("  " + " | ".join(stored))
    if errors:
        result.append(f"  Errors: {'; '.join(errors)}")
    return "\n".join(result)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
