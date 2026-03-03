"""
AxiomBrain — Database Migration Runner
Run with:  python -m axiom_brain.database.migrate
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

from axiom_brain.config import get_settings


MIGRATIONS_DIR = Path(__file__).parent / "migrations"


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

        print("\nAll migrations applied successfully.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
