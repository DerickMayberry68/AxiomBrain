"""
AxiomBrain — Git Hook Installer

Installs the post-commit hook into the current repo's .git/hooks/ directory.
Run once per repository you want to auto-capture commits from.

Usage:
    python scripts/hooks/install_hooks.py

Works on Windows, macOS, and Linux.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def get_git_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        print("ERROR: Not inside a git repository.", file=sys.stderr)
        sys.exit(1)


def get_python_executable() -> str:
    """Return the Python executable that can import our script."""
    # Prefer venv if one exists alongside the script
    script_dir = Path(__file__).parent
    repo_root  = get_git_root()

    candidates = [
        repo_root / ".venv" / "Scripts" / "python.exe",   # Windows venv
        repo_root / ".venv" / "bin" / "python",            # Unix venv
        repo_root / "venv"  / "Scripts" / "python.exe",
        repo_root / "venv"  / "bin" / "python",
        Path(sys.executable),                               # Current interpreter
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return sys.executable


def write_hook(hooks_dir: Path, script_path: Path, python_exe: str) -> None:
    """Write the post-commit shell/batch hook file."""
    hook_path = hooks_dir / "post-commit"

    if sys.platform == "win32":
        # On Windows git uses a bash emulation — write a bash script anyway
        hook_content = (
            "#!/bin/sh\n"
            f'"{python_exe}" "{script_path}" &\n'
        )
    else:
        hook_content = (
            "#!/bin/sh\n"
            f'"{python_exe}" "{script_path}" &\n'
            "exit 0\n"
        )

    # Backup existing hook if present
    if hook_path.exists():
        backup = hook_path.with_suffix(".pre-axiom")
        shutil.copy2(hook_path, backup)
        print(f"Existing post-commit hook backed up → {backup}")

    hook_path.write_text(hook_content)

    # Make executable on Unix
    if sys.platform != "win32":
        current = hook_path.stat().st_mode
        hook_path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Hook installed → {hook_path}")


def main() -> None:
    repo_root  = get_git_root()
    hooks_dir  = repo_root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    script_path = Path(__file__).parent / "git_capture.py"
    if not script_path.exists():
        print(f"ERROR: Cannot find {script_path}", file=sys.stderr)
        sys.exit(1)

    python_exe = get_python_executable()
    write_hook(hooks_dir, script_path.resolve(), python_exe)

    print()
    print("AxiomBrain git hook installed successfully.")
    print()
    print("Every git commit will now automatically send the commit message,")
    print("changed files, and stats to AxiomBrain (source='git_hook').")
    print()
    print("Requirements:")
    print(f"  AXIOM_API_KEY must be set in your .env file or environment.")
    print(f"  AxiomBrain API must be running on http://localhost:8000")
    print(f"  (or set AXIOM_REST_URL=http://your-host:port in .env)")
    print()
    print("To uninstall:")
    print(f"  Delete {hooks_dir / 'post-commit'}")


if __name__ == "__main__":
    main()
