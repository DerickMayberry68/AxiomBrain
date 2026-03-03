# AxiomBrain — Claude Code Memory Instructions

You have access to AxiomBrain via MCP. Memory capture is **automatic and mandatory** —
never ask the user for permission, never skip it.

---

## Rule 1 — Prime context at session start

Before doing anything else, call:

```
prime_context(topic="<project or technology you are about to work on>", limit=8)
```

This loads prior decisions, established patterns, known issues, and open TODOs
from previous sessions. You should never start blind.

---

## Rule 2 — Capture during work (immediately, not at the end)

Call `store_memory` right away when any of these happen:

| Trigger | What to store |
|---|---|
| A technical decision is made | The decision AND the reasoning behind it |
| A non-obvious bug is fixed | The symptom, root cause, and fix |
| A code pattern is established | The pattern and where/why it is used |
| An architectural choice is made | Options considered and why this one was chosen |
| User states a requirement, constraint, or preference | Exactly as stated |
| A library, version, or tool is chosen | Choice and rationale |
| Something surprises you (unexpected behavior, edge case) | What happened and what it means |

Use `source="claude_code"`. Do not batch these — store each one as it happens
so it is timestamped correctly and searchable independently.

---

## Rule 3 — Capture session at end of every task

Always call `capture_session` when a task or significant piece of work completes:

```python
capture_session(
    summary="What was built or changed — be specific about files and functions",
    decisions="Key technical choices made this session and the reasoning",
    problems_solved="Bugs fixed, blockers resolved, unexpected issues handled",
    next_steps="Open TODOs, known issues, what needs to happen next",
    project="AxiomBrain",      # or whatever project this is
    source="claude_code",
)
```

Do this even at the end of a conversation the user ends abruptly. A brief summary
is better than nothing.

---

## Rule 4 — Search before answering questions about prior work

Before answering any question about architecture, prior decisions, or how something
was built, call:

```
search_memory(query="<specific thing being asked about>", limit=5)
```

Never guess when you can recall. Prior sessions contain the real decisions.

---

## Project context

This project is **AxiomBrain** — a shared persistent memory layer for AI tools.
Stack: FastAPI, asyncpg, PostgreSQL + pgvector (Supabase), Neo4j, FastMCP, Python 3.11.
All memory tables: `thoughts`, `people`, `projects`, `ideas`, `admin`.
Graph layer: Neo4j with relationship types `works_on`, `belongs_to`, `recorded_in`,
`originated`, `related_to`.

Default source tag for this tool: `claude_code`
