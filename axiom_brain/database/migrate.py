"""
AxiomBrain — Database Migration Runner
Run with:  python -m axiom_brain.database.migrate
"""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

import asyncpg

from axiom_brain.config import get_settings


MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Tables that need workspace_id backfilled in the post-005 hook
_WORKSPACE_TABLES = ("thoughts", "admin", "ideas", "people", "projects", "summaries", "relationships")


async def _post_migrate_005(conn, settings) -> None:
    """
    Post-migration hook for 005_workspaces.sql:
    1. Insert the default workspace using the configured API key.
    2. Backfill workspace_id on all existing memory rows.
    3. Set workspace_id NOT NULL on all tables.
    """
    print("    → creating default workspace ...", end="", flush=True)

    # Use the configured API key as the default workspace key.
    # If it's the placeholder, generate a real one and warn.
    api_key = settings.axiom_api_key
    if not api_key or api_key == "change-me-in-env":
        api_key = secrets.token_urlsafe(32)
        print(f"\n    ⚠  AXIOM_API_KEY not set — generated key: {api_key}")
        print("       Add this to your .env as AXIOM_API_KEY= before restarting.")

    workspace_id = await conn.fetchval(
        """
        INSERT INTO workspaces (name, slug, api_key, is_active, is_admin)
        VALUES ('Default', 'default', $1, TRUE, TRUE)
        ON CONFLICT (slug) DO UPDATE SET api_key = EXCLUDED.api_key
        RETURNING id
        """,
        api_key,
    )
    print(f" id={workspace_id}")

    print("    → backfilling workspace_id on all tables ...", end="", flush=True)
    for table in _WORKSPACE_TABLES:
        # Only update rows that don't yet have a workspace_id
        try:
            updated = await conn.fetchval(
                f"UPDATE {table} SET workspace_id = $1 WHERE workspace_id IS NULL RETURNING count(*)",
                workspace_id,
            )
            # fetchval returns None if no rows — treat as 0
        except Exception:
            pass  # table may not exist yet (e.g. summaries added in 003)
    print(" done")

    print("    → enforcing NOT NULL on workspace_id ...", end="", flush=True)
    for table in _WORKSPACE_TABLES:
        try:
            await conn.execute(
                f"ALTER TABLE {table} ALTER COLUMN workspace_id SET NOT NULL"
            )
        except Exception:
            pass  # skip if column doesn't exist on this instance
    print(" done")


async def run_migrations() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.database_url)

    try:
        # Ensure migration tracking table exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _axiom_migrations (
                id          SERIAL PRIMARY KEY,
                filename    TEXT UNIQUE NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            print("No migration files found.")
            return

        for migration_file in migration_files:
            already_applied = await conn.fetchval(
                "SELECT 1 FROM _axiom_migrations WHERE filename = $1",
                migration_file.name,
            )
            if already_applied:
                print(f"  [skip]    {migration_file.name}")
                continue

            print(f"  [apply]   {migration_file.name} ...", end="", flush=True)
            sql = migration_file.read_text(encoding="utf-8")
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _axiom_migrations (filename) VALUES ($1)",
                migration_file.name,
            )
            print(" done")

            # Post-migration Python hooks
            if migration_file.name == "005_workspaces.sql":
                await _post_migrate_005(conn, settings)

        print("\nAll migrations applied successfully.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
