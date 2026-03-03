"""
AxiomBrain — Custom Agent Integration Example
===============================================
This script shows how to embed AxiomBrain into any custom Python
agent, automation script, or workflow tool.

Two patterns are demonstrated:
  1. Sync agent  — simple scripts, CLI tools, one-shot automations
  2. Async agent — LangGraph, asyncio pipelines, concurrent workflows

Run from project root with venv activated:
    python examples/example_agent.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

from axiom_brain.client import AxiomBrainClient, AsyncAxiomBrainClient

API_KEY  = os.getenv("AXIOM_API_KEY", "")
BASE_URL = f"http://localhost:{os.getenv('AXIOM_REST_PORT', '8000')}"


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 1: Synchronous Agent
# Use this for simple scripts, CLI tools, and one-shot automations.
# ─────────────────────────────────────────────────────────────────────────────

class SimpleConsultingAgent:
    """
    Example: A consulting agent that logs decisions and can recall
    project context on demand.
    """

    def __init__(self) -> None:
        self.brain = AxiomBrainClient(base_url=BASE_URL, api_key=API_KEY)
        self.name  = "consulting_agent"

    def log_decision(self, decision: str) -> str:
        """Store an architectural or business decision."""
        result = self.brain.ingest(
            content=decision,
            source=self.name,
            target_table="thoughts",
        )
        return result.get("thought_id", "unknown")

    def log_project_note(self, note: str) -> str:
        """Store a project-level note (routes to projects table)."""
        result = self.brain.ingest(
            content=note,
            source=self.name,
            # No target_table — let the classifier decide
        )
        return result.get("thought_id", "unknown")

    def recall(self, topic: str, limit: int = 5) -> list:
        """Retrieve relevant memories before making a decision."""
        return self.brain.search(query=topic, limit=limit)

    def get_project_context(self, project_name: str) -> list:
        """Pull all memories related to a specific project."""
        return self.brain.search(
            query=project_name,
            tables=["projects", "thoughts"],
            limit=10,
        )

    def run_demo(self) -> None:
        print("\n── Sync Agent Demo ───────────────────────────────────────────")

        # 1. Store a decision
        tid = self.log_decision(
            "Chose async FastAPI over Flask for AxiomBrain REST layer "
            "due to native async/await support and better performance under concurrent load."
        )
        print(f"  Logged decision → {tid}")

        # 2. Store a project note
        tid = self.log_project_note(
            "AxiomBrain project milestone: all four LLM tools (Claude Code, Cursor, "
            "Antigravity, Gemini CLI) connected via MCP. Custom agents via REST API."
        )
        print(f"  Logged project note → {tid}")

        # 3. Recall context before making next decision
        print("\n  Recalling context for 'API framework decisions'...")
        results = self.recall("API framework decisions", limit=3)
        for r in results:
            print(f"    [{r.get('similarity', 0):.0%}] {r.get('content', '')[:80]}...")

        print("\n  Done.\n")


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 2: Async Agent
# Use this for LangGraph pipelines, concurrent task runners, or any
# asyncio-based workflow.
# ─────────────────────────────────────────────────────────────────────────────

class AsyncConsultingAgent:
    """
    Async version — drop this pattern into LangGraph nodes,
    asyncio task queues, or any async framework.
    """

    def __init__(self) -> None:
        self.brain = AsyncAxiomBrainClient(base_url=BASE_URL, api_key=API_KEY)
        self.name  = "async_consulting_agent"

    async def log(self, content: str) -> str:
        result = await self.brain.ingest(content=content, source=self.name)
        return result.get("thought_id", "unknown")

    async def recall(self, query: str, limit: int = 5) -> list:
        return await self.brain.search(query=query, limit=limit)

    async def run_demo(self) -> None:
        print("\n── Async Agent Demo ──────────────────────────────────────────")

        # Run two ingests concurrently
        tid1, tid2 = await asyncio.gather(
            self.log("Async agent test: ingesting two memories concurrently."),
            self.log("Second concurrent memory from the async agent demo."),
        )
        print(f"  Concurrent ingest → {tid1}")
        print(f"  Concurrent ingest → {tid2}")

        # Search
        print("\n  Searching for 'concurrent async'...")
        results = await self.recall("concurrent async", limit=3)
        for r in results:
            print(f"    [{r.get('similarity', 0):.0%}] {r.get('content', '')[:80]}...")

        print("\n  Done.\n")


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 3: Session Bootstrap
# Call this at the START of any agent session to load relevant context
# before the agent starts working. Prevents the agent from repeating
# decisions already made or forgetting project state.
# ─────────────────────────────────────────────────────────────────────────────

def bootstrap_session(task_description: str, top_k: int = 5) -> str:
    """
    Pull relevant memories from AxiomBrain and return them as a
    context string you can prepend to any LLM prompt.

    Example:
        context = bootstrap_session("Refactor the authentication module")
        prompt  = context + "\\n\\nTask: Refactor the authentication module..."
    """
    brain   = AxiomBrainClient(base_url=BASE_URL, api_key=API_KEY)
    results = brain.search(query=task_description, limit=top_k)

    if not results:
        return ""

    lines = ["## Relevant context from AxiomBrain\n"]
    for r in results:
        content = r.get("content", "")
        table   = r.get("table", "?")
        score   = r.get("similarity", 0)
        lines.append(f"- [{table} / {score:.0%}] {content}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not API_KEY:
        print("AXIOM_API_KEY not set. Check your .env file.")
        sys.exit(1)

    # Run sync demo
    sync_agent = SimpleConsultingAgent()
    sync_agent.run_demo()

    # Run async demo
    async_agent = AsyncConsultingAgent()
    asyncio.run(async_agent.run_demo())

    # Demo session bootstrap
    print("── Session Bootstrap Demo ────────────────────────────────────")
    context = bootstrap_session("LLM tool integrations and MCP connections")
    print(context if context else "  (no relevant memories found)")
    print()
