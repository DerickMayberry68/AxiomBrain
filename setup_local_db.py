"""
AxiomBrain — Local PostgreSQL Setup Script
Run this ONCE before your first migration to:
  1. Verify PostgreSQL connectivity
  2. Create the 'axiombrain' database if it doesn't exist
  3. Check whether pgvector is installed
  4. Print guidance if pgvector is missing

Usage:
    python setup_local_db.py
    python setup_local_db.py --host localhost --port 5432 --user postgres
"""

from __future__ import annotations

import argparse
import getpass
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AxiomBrain local PostgreSQL setup")
    p.add_argument("--host",   default="localhost", help="PostgreSQL host (default: localhost)")
    p.add_argument("--port",   default=5432, type=int, help="PostgreSQL port (default: 5432)")
    p.add_argument("--user",   default="postgres", help="Superuser name (default: postgres)")
    p.add_argument("--dbname", default="axiombrain", help="Target database name (default: axiombrain)")
    p.add_argument("--password", default=None, help="Password (prompted if omitted)")
    return p.parse_args()


def main() -> None:
    try:
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    except ImportError:
        print("\n[ERROR] psycopg2 is not installed.")
        print("  Run:  pip install psycopg2-binary")
        sys.exit(1)

    args = parse_args()

    password = args.password
    if password is None:
        password = getpass.getpass(
            f"Password for PostgreSQL user '{args.user}' (leave blank for trust auth): "
        )

    # ── Step 1: Connect to postgres (maintenance DB) ──────────────────────────
    print(f"\nConnecting to PostgreSQL at {args.host}:{args.port} as '{args.user}'...")
    try:
        conn = psycopg2.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password or None,
            dbname="postgres",
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        print("  [OK] Connected to PostgreSQL.")
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Could not connect: {e}")
        print("\nTroubleshooting:")
        print("  - Make sure PostgreSQL is running")
        print("  - Check your password")
        print("  - Verify pg_hba.conf allows local connections")
        sys.exit(1)

    cur = conn.cursor()

    # ── Step 2: Create the axiombrain database ────────────────────────────────
    cur.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (args.dbname,),
    )
    exists = cur.fetchone()

    if exists:
        print(f"  [OK] Database '{args.dbname}' already exists.")
    else:
        print(f"  Creating database '{args.dbname}'...")
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.dbname)))
        print(f"  [OK] Database '{args.dbname}' created.")

    cur.close()
    conn.close()

    # ── Step 3: Connect to axiombrain and check pgvector ─────────────────────
    print(f"\nConnecting to '{args.dbname}' database...")
    try:
        conn2 = psycopg2.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password or None,
            dbname=args.dbname,
        )
        conn2.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    except psycopg2.OperationalError as e:
        print(f"[ERROR] Could not connect to '{args.dbname}': {e}")
        sys.exit(1)

    cur2 = conn2.cursor()

    # Check if pgvector is available (either installed or in available_extensions)
    cur2.execute("""
        SELECT name, installed_version, default_version
        FROM pg_available_extensions
        WHERE name = 'vector'
    """)
    pgvector_row = cur2.fetchone()

    print("\n── pgvector Status ──────────────────────────────────────────")
    if pgvector_row is None:
        print("  [MISSING] pgvector is NOT available on this PostgreSQL installation.")
        _print_pgvector_install_guide()
    elif pgvector_row[1] is not None:
        print(f"  [OK] pgvector {pgvector_row[1]} is installed and enabled.")
    else:
        print(f"  [FOUND] pgvector {pgvector_row[2]} is available but not yet enabled.")
        print("  Enabling it now in the axiombrain database...")
        try:
            cur2.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print("  [OK] pgvector extension enabled.")
        except psycopg2.Error as e:
            print(f"  [ERROR] Could not enable pgvector: {e}")
            print("  You may need to run this as a superuser, or install pgvector first.")
            _print_pgvector_install_guide()

    # ── Step 4: Print the correct DATABASE_URL ────────────────────────────────
    pw_part = f":{password}" if password else ""
    db_url  = f"postgresql://{args.user}{pw_part}@{args.host}:{args.port}/{args.dbname}"

    print("\n── Your DATABASE_URL ────────────────────────────────────────")
    print(f"  {db_url}")
    print("\n  Set this in your .env file:")
    print(f"  DATABASE_URL={db_url}")

    print("\n── Next Steps ───────────────────────────────────────────────")
    print("  1. Copy .env.example to .env and set your DATABASE_URL and API keys")
    print("  2. Run:  python -m axiom_brain.database.migrate")
    print("  3. Run:  uvicorn axiom_brain.api.main:app --reload --port 8000")
    print("  4. Run:  python -m axiom_brain.mcp.server")
    print()

    cur2.close()
    conn2.close()


def _print_pgvector_install_guide() -> None:
    print("""
  ── How to install pgvector on Windows ──────────────────────────────────
  Option A — Pre-built binaries (easiest):
    1. Find your PostgreSQL version:
       SELECT version(); -- in psql or pgAdmin
    2. Download the matching .zip from:
       https://github.com/pgvector/pgvector/releases
       (e.g. pgvector-0.8.0-pg16-windows-x86_64.zip for PG 16)
    3. Extract and copy files:
         vector.dll  → C:\\Program Files\\PostgreSQL\\<ver>\\lib\\
         vector.control  → C:\\Program Files\\PostgreSQL\\<ver>\\share\\extension\\
         vector--*.sql   → C:\\Program Files\\PostgreSQL\\<ver>\\share\\extension\\
    4. Restart the PostgreSQL service (services.msc)
    5. Re-run this script

  Option B — Build from source (requires Visual Studio + nmake):
    See: https://github.com/pgvector/pgvector#windows

  Option C — Use Supabase (pgvector is pre-installed):
    Update DATABASE_URL in .env to your Supabase connection string.
  ─────────────────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()
