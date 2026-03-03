#!/usr/bin/env python
"""
brain.py — AxiomBrain Quick CLI
================================
A standalone command-line tool for storing and searching memories
without opening an IDE.

Usage (from project root with venv activated):

    python brain.py store "Decided to use Redis for session caching on the Axiom project"
    python brain.py search "caching decisions"
    python brain.py search "caching decisions" --limit 5 --table thoughts
    python brain.py stats
    python brain.py thoughts
    python brain.py thoughts --source claude_code

Shortcuts:
    python brain.py s  "quick note"     # alias for store
    python brain.py q  "query"          # alias for search
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── Load .env from project root ───────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent
_ENV_FILE = _PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ENV_FILE)
except ImportError:
    pass  # python-dotenv not installed; rely on real env vars

# ── Client import ─────────────────────────────────────────────────────────────
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from axiom_brain.client import AxiomBrainClient
except ImportError as exc:
    print(f"[brain.py] Cannot import AxiomBrainClient: {exc}")
    print("  Make sure you're running with the .venv activated:")
    print("  .venv\\Scripts\\activate  (Windows)")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY  = os.getenv("AXIOM_API_KEY", "")
API_PORT = os.getenv("AXIOM_REST_PORT", "8000")
BASE_URL = f"http://localhost:{API_PORT}"


def get_client() -> AxiomBrainClient:
    if not API_KEY:
        print("[brain.py] AXIOM_API_KEY not set. Check your .env file.")
        sys.exit(1)
    return AxiomBrainClient(base_url=BASE_URL, api_key=API_KEY)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_results(results: list) -> None:
    if not results:
        print("  (no results found)")
        return
    for i, r in enumerate(results, 1):
        score   = r.get("similarity", 0)
        table   = r.get("source_table", "?")
        content = r.get("primary_text", "")
        topics  = ", ".join(r.get("topics") or [])
        print(f"\n  [{i}] {table}  {score:.0%} match")
        print(f"      {content}")
        if topics:
            print(f"      Topics: {topics}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_store(args: argparse.Namespace) -> None:
    brain  = get_client()
    source = args.source or "brain_cli"
    result = brain.ingest(
        content=args.content,
        source=source,
        target_table=args.table or None,
    )
    print(f"\n✓ Stored to AxiomBrain")
    print(f"  Thought ID : {result.get('thought_id', '?')}")
    print(f"  Type       : {result.get('content_type', '?')}")
    print(f"  Routed to  : {result.get('routed_to', '?')}")
    print(f"  Confidence : {result.get('confidence', 0):.0%}")
    topics = result.get("topics") or []
    if topics:
        print(f"  Topics     : {', '.join(topics)}")


def cmd_search(args: argparse.Namespace) -> None:
    brain   = get_client()
    tables  = [args.table] if args.table else None
    results = brain.search(
        query=args.query,
        tables=tables,
        limit=args.limit,
        topic_filter=args.topic or None,
    )
    print(f"\nSearch: \"{args.query}\"  ({len(results)} result{'s' if len(results) != 1 else ''})")
    _print_results(results)
    print()


def cmd_stats(args: argparse.Namespace) -> None:
    brain  = get_client()
    data   = brain.stats()
    tables = data.get("tables", [])
    total  = sum(t.get("row_count", 0) for t in tables)
    print(f"\n── AxiomBrain Stats ──────────────────────")
    print(f"  Total memories : {total}")
    for t in tables:
        name      = t.get("table", "?")
        count     = t.get("row_count", 0)
        updated   = (t.get("last_update") or "never")[:19].replace("T", " ")
        print(f"  {name:<18}: {count:>4}   last: {updated}")
    print()


def cmd_thoughts(args: argparse.Namespace) -> None:
    brain  = get_client()
    data   = brain.list_thoughts(
        limit=args.limit,
        offset=args.offset,
        source=args.source or None,
    )
    items = data.get("items", [])
    total = data.get("total", 0)
    print(f"\n── Recent Thoughts ({len(items)} of {total}) ──────────────")
    for t in items:
        ts      = t.get("created_at", "")[:19].replace("T", " ")
        source  = t.get("source", "?")
        content = t.get("content", "")
        topics  = ", ".join(t.get("topics") or [])
        tid     = t.get("id", "?")
        print(f"\n  [{ts}] {source}")
        print(f"  ID: {tid}")
        print(f"  {content}")
        if topics:
            print(f"  Topics: {topics}")
    print()


def cmd_health(args: argparse.Namespace) -> None:
    brain = get_client()
    data  = brain.health()
    db_ok = data.get("db_ok", False)
    print(f"\n── AxiomBrain Health ─────────────────────")
    print(f"  Status  : {data.get('status', '?')}")
    print(f"  Version : {data.get('version', '?')}")
    print(f"  Database: {'✓ connected' if db_ok else '✗ unreachable'}")
    print()


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brain",
        description="AxiomBrain Quick CLI — store and search shared AI memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python brain.py store "Decided to use Redis for session caching"
  python brain.py store "Meeting with client at 2pm" --source calendar_agent
  python brain.py search "caching decisions"
  python brain.py search "client meetings" --limit 5
  python brain.py stats
  python brain.py thoughts --limit 10
  python brain.py health
        """,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # store / s
    for alias in ("store", "s"):
        p = sub.add_parser(alias, help="Store a memory in AxiomBrain" if alias == "store" else argparse.SUPPRESS)
        p.add_argument("content", help="Text content to store")
        p.add_argument("--source", "-s", default="brain_cli", help="Source label (default: brain_cli)")
        p.add_argument("--table",  "-t", choices=["thoughts","people","projects","ideas","admin"],
                       help="Force routing to a specific table (optional)")

    # search / q
    for alias in ("search", "q"):
        p = sub.add_parser(alias, help="Semantic search" if alias == "search" else argparse.SUPPRESS)
        p.add_argument("query", help="Search query")
        p.add_argument("--limit",  "-n", type=int, default=10, help="Max results (default: 10)")
        p.add_argument("--table",  "-t", choices=["thoughts","people","projects","ideas","admin"],
                       help="Restrict search to one table")
        p.add_argument("--topic",  help="Filter by topic tag")

    # stats
    sub.add_parser("stats", help="Show memory counts per table")

    # thoughts
    p = sub.add_parser("thoughts", help="List recent thoughts (audit log)")
    p.add_argument("--limit",  "-n", type=int, default=20, help="Number to show (default: 20)")
    p.add_argument("--offset", "-o", type=int, default=0,  help="Pagination offset")
    p.add_argument("--source", "-s", help="Filter by source label")

    # health
    sub.add_parser("health", help="Check API + database connectivity")

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    dispatch = {
        "store":    cmd_store,
        "s":        cmd_store,
        "search":   cmd_search,
        "q":        cmd_search,
        "stats":    cmd_stats,
        "thoughts": cmd_thoughts,
        "health":   cmd_health,
    }

    if args.command in dispatch:
        try:
            dispatch[args.command](args)
        except Exception as exc:
            print(f"\n[brain.py] Error: {exc}")
            print("  Is the AxiomBrain API running?  uvicorn axiom_brain.api.main:app --port 8000")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
