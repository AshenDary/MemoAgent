"""Verify the live Supabase schema after manual SQL Editor application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.embedder import get_supabase_client


TABLE_NAMES = ("transcript_chunks", "api_keys", "agent_sessions", "audit_logs")


def main() -> int:
    """Check that the live Supabase schema exists and RLS is enabled."""
    load_dotenv()

    if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        logger.error("Missing SUPABASE_SERVICE_ROLE_KEY; schema verification requires server-side access")
        return 1

    client = get_supabase_client()
    all_tables_present = True
    for table_name in TABLE_NAMES:
        if not _table_exists(client, table_name):
            all_tables_present = False

    rls_ok = True
    db_url = os.getenv("SUPABASE_DB_URL")
    if db_url:
        rls_ok = _check_rls_flags(db_url=db_url)
    else:
        logger.warning("SUPABASE_DB_URL is not set; skipping direct RLS verification")

    if all_tables_present and rls_ok:
        logger.info("Supabase schema verification passed")
        return 0

    logger.error("Supabase schema verification failed")
    return 1


def _table_exists(client, table_name: str) -> bool:
    """Check that one table is queryable through the Supabase client."""
    try:
        client.table(table_name).select("*").limit(1).execute()
    except Exception as exc:
        logger.error("Table {} is not queryable: {}", table_name, exc)
        return False

    logger.info("Verified table exists: {}", table_name)
    return True


def _check_rls_flags(*, db_url: str) -> bool:
    """Confirm row-level security is enabled for the tracked public tables."""
    query = """
        select c.relname, c.relrowsecurity
        from pg_class as c
        join pg_namespace as n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relname = any(%s)
        order by c.relname;
    """

    found_flags: dict[str, bool] = {}
    with psycopg.connect(db_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (list(TABLE_NAMES),))
            for relname, relrowsecurity in cursor.fetchall():
                found_flags[str(relname)] = bool(relrowsecurity)

    missing_tables = [table_name for table_name in TABLE_NAMES if table_name not in found_flags]
    for table_name in missing_tables:
        logger.error("Missing table in pg_catalog: {}", table_name)

    disabled_rls = [table_name for table_name, enabled in found_flags.items() if not enabled]
    for table_name in disabled_rls:
        logger.error("RLS is disabled for table: {}", table_name)

    if missing_tables or disabled_rls:
        return False

    for table_name in TABLE_NAMES:
        logger.info("Verified RLS enabled for table: {}", table_name)

    return True


if __name__ == "__main__":
    sys.exit(main())