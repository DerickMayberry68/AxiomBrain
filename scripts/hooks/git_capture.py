"""
AxiomBrain — Git Commit Auto-Capture

Called by the post-commit hook after every `git commit`.
Reads commit metadata from git and sends it to AxiomBrain automatically.

No AI involvement — this captures 100% automatically.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
import urllib.error
import json
from pathlib import Path


def run(cmd: list[str]) -> str:
    """Run a git command and return stdout, empty string on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            cwd=os.environ.get("GIT_DIR", "."),
        )
        return result.stdout.strip()
    except Exception:
        return ""


def build_commit_content() -> str:
    """Build a rich memory string from the latest commit."""
    sha     = run(["git", "log", "-1", "--pretty=%H"])
    short   = sha[:8] if sha else "unknown"
    msg     = run(["git", "log", "-1", "--pretty=%B"])
    author  = run(["git", "log", "-1", "--pretty=%an"])
    date    = run(["git", "log", "-1", "--pretty=%ci"])
    branch  = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])

    # Files changed (limit to avoid huge payloads)
    files_raw = run(["git", "diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"])
    files = files_raw.splitlines()[:20]
    files_str = ", ".join(files) if files else "no files"
    if len(files_raw.splitlines()) > 20:
        files_str += f" (+{len(files_raw.splitlines()) - 20} more)"

    # Brief stats
    stats = run(["git", "diff-tree", "--no-commit-id", "-r", "--stat", "HEAD"])
    stat_summary = stats.splitlines()[-1] if stats else ""

    content = (
        f"[git commit {short}] {msg}\n"
        f"Branch: {branch} | Author: {author} | Date: {date}\n"
        f"Files changed: {files_str}\n"
    )
    if stat_summary:
        content += f"Stats: {stat_summary}\n"

    return content.strip()


def send_to_axiombrain(content: str, api_url: str, api_key: str) -> bool:
    """POST the commit content to AxiomBrain /ingest. Returns True on success."""
    payload = json.dumps({
        "content": content,
        "source":  "git_hook",
    }).encode()

    req = urllib.request.Request(
        f"{api_url}/ingest",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key":    api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read())
            print(f"[AxiomBrain] Commit captured → {body.get('thought_id', '?')[:8]}...")
            return True
    except urllib.error.HTTPError as exc:
        print(f"[AxiomBrain] Capture failed: HTTP {exc.code}", file=sys.stderr)
        return False
    except Exception as exc:
        # Never block a commit — silently fail if API is down
        print(f"[AxiomBrain] Capture skipped (API unavailable): {exc}", file=sys.stderr)
        return False


def main() -> None:
    # Resolve config — prefer environment vars, fall back to .env in repo root
    api_url = os.environ.get("AXIOM_REST_URL", "")
    api_key = os.environ.get("AXIOM_API_KEY", "")

    if not api_url or not api_key:
        # Try loading from .env in the git repo root
        repo_root = run(["git", "rev-parse", "--show-toplevel"])
        env_path  = Path(repo_root) / ".env" if repo_root else None

        if env_path and env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key   = key.strip()
                value = value.strip().strip('"').strip("'")
                if key == "AXIOM_REST_URL":
                    api_url = value
                elif key == "AXIOM_REST_PORT" and not api_url:
                    api_url = f"http://localhost:{value}"
                elif key == "AXIOM_API_KEY":
                    api_key = value

    # Default fallback
    if not api_url:
        api_url = "http://localhost:8000"

    if not api_key:
        print("[AxiomBrain] AXIOM_API_KEY not set — skipping commit capture.", file=sys.stderr)
        return

    content = build_commit_content()
    if content:
        send_to_axiombrain(content, api_url, api_key)


if __name__ == "__main__":
    main()
