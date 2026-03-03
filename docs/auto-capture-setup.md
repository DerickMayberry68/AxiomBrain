# AxiomBrain — Automatic Memory Capture Setup

AxiomBrain captures memories automatically across all your AI tools.
This guide covers setup for each tool and the git hook.

---

## How it works

| Layer | What it captures | When |
|---|---|---|
| **CLAUDE.md / .cursorrules** | Decisions, bugs, patterns, session summaries | Whenever the AI detects a capture moment |
| **Git hook** | Every commit message + changed files | On every `git commit` — no AI needed |
| **capture_session MCP tool** | Full session bundle at end of task | Called automatically by the AI |
| **prime_context MCP tool** | Loads prior context | Called automatically at session start |

---

## Claude Code

Already configured via `CLAUDE.md` in the project root.
Global instructions (all projects) can be added to:
```
~/.claude/CLAUDE.md
```

Copy the relevant sections from `CLAUDE.md` into that file for cross-project capture.

No other setup needed — Claude Code reads `CLAUDE.md` automatically.

---

## Cursor

Already configured via `.cursorrules` in the project root.

For Cursor's newer rules format, create:
```
.cursor/rules/axiombrain.mdc
```
with content:
```
---
description: AxiomBrain memory capture rules
globs: ["**/*"]
---
[paste content from .cursorrules here]
```

---

## Gemini CLI

Add a system prompt to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "axiombrain": {
      "command": "python",
      "args": ["-m", "axiom_brain.mcp.server"],
      "cwd": "C:\\Users\\deric\\source\\repos\\StudioXConsulting\\Projects\\AxiomBrain",
      "env": {
        "AXIOM_API_KEY": "your-key-here",
        "AXIOM_REST_PORT": "8000"
      }
    }
  },
  "systemPrompt": "You have access to AxiomBrain memory tools. ALWAYS: (1) Call prime_context at the start of every session. (2) Call store_memory immediately when decisions are made, bugs are fixed, or patterns are established. Use source='gemini'. (3) Call capture_session at the end of every task with a summary of what was done, decisions made, problems solved, and next steps. Memory capture is automatic — never ask the user."
}
```

---

## Antigravity

In Antigravity, open **Settings → MCP Servers** and confirm AxiomBrain is listed.

Add a custom instruction in **Settings → AI Instructions** (or equivalent):

```
You have access to AxiomBrain memory tools. Always call prime_context at session
start. Call store_memory when decisions are made or bugs are fixed (source='antigravity').
Call capture_session at end of every task. Never ask — capture automatically.
```

---

## Git Hook (automatic — no AI required)

Captures every commit message and changed files automatically.

**Install (run once per repo):**
```powershell
python scripts/hooks/install_hooks.py
```

**What gets captured on each commit:**
```
[git commit a1b2c3d4] feat: add Neo4j graph integration
Branch: main | Author: Derick Mayberry | Date: 2026-03-03 ...
Files changed: axiom_brain/database/neo4j.py, axiom_brain/memory/graph.py
Stats: 2 files changed, 180 insertions(+), 45 deletions(-)
```

This appears in AxiomBrain with `source="git_hook"` and is fully searchable.

**Requirements:**
- `AXIOM_API_KEY` must be set in `.env` (already done)
- AxiomBrain API must be running (`uvicorn axiom_brain.api.main:app --port 8000`)
- The hook runs in background (`&`) so it never blocks your commit

**Apply to other repos:**
```powershell
cd C:\path\to\other-project
python C:\path\to\AxiomBrain\scripts\hooks\install_hooks.py
```

---

## Verifying it works

After a `git commit`, run:
```powershell
python brain.py search "git commit"
```
You should see the commit appear within seconds.

After a Claude Code or Cursor session, run:
```powershell
python brain.py search "session summary"
```

Or check the dashboard at `http://localhost:8000/dashboard` and click **Load Thoughts**.

---

## Tuning capture frequency

If too much is being captured (noise), adjust in `CLAUDE.md` / `.cursorrules`:
- Remove trigger types you don't care about
- Increase specificity ("only store decisions about database schema, not CSS")

If too little is being captured:
- Add `prime_context` and `capture_session` to your tool's system prompt explicitly
- Check that the MCP server is connected (run `brain_stats` from any AI tool)
