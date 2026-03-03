# AxiomBrain

**Shared persistent memory layer for LLM tools.**

AxiomBrain gives Claude Code, Codex, Cursor, and custom agents a single shared brain — a PostgreSQL + pgvector store that persists context, decisions, ideas, and tasks across all sessions and tools.

> *"When intelligence is abundant, context becomes the scarce resource."* — Nate B. Jones

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Docker (for local PostgreSQL) OR a Supabase project
- An [OpenRouter](https://openrouter.ai) API key

### 2. Setup

```bash
# Clone and enter the project
cd AxiomBrain

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env — set OPENROUTER_API_KEY and AXIOM_API_KEY
```

### 3. Start the Database

```bash
# Local PostgreSQL with pgvector
docker-compose up -d

# Apply schema
python -m axiom_brain.database.migrate
```

### 4. Start the Services

```bash
# Terminal 1 — REST API (port 8000)
uvicorn axiom_brain.api.main:app --reload --port 8000

# Terminal 2 — MCP Server (for Claude Code / Cursor)
python -m axiom_brain.mcp.server
```

### 5. Verify

```bash
curl http://localhost:8000/health
```

---

## Integrating with Claude Code

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "axiombrain": {
      "command": "python",
      "args": ["-m", "axiom_brain.mcp.server"],
      "env": {
        "AXIOM_API_KEY": "your-key-here"
      }
    }
  }
}
```

---

## Integrating with Cursor

Add `.mcp.json` at your project root with the same config block above.

---

## Integrating with Custom Agents

```python
from axiom_brain.client import AxiomBrainClient

brain = AxiomBrainClient(base_url='http://localhost:8000', api_key='your-key')

# Store a decision
brain.ingest('Decided to use PostgreSQL for all persistence', source='my_agent')

# Recall relevant context
results = brain.search('database decisions', limit=5)
for r in results:
    print(f"[{r['source_table']}] {r['primary_text']}")
```

---

## API Docs

Once the REST service is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc:       http://localhost:8000/redoc

## Web Dashboard (Phase 4)

Use the built-in browser UI to work with memory without manual API calls:
- Dashboard:   http://localhost:8000/dashboard

The dashboard uses the same API security model as the REST endpoints. Enter your
`AXIOM_API_KEY` in the page and it will send requests with the `X-API-Key` header.

---

## Architecture

See `docs/AxiomBrain_Architecture.docx` for the full architecture document.
