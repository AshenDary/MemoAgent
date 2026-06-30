"""Apply the local Supabase schema through a direct Postgres connection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from loguru import logger


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "supabase" / "schema.sql"


# WHAT THIS DOES: Reads SUPABASE_DB_URL and executes supabase/schema.sql.
# WHY THIS MATTERS: The Supabase REST API key cannot run arbitrary SQL schema setup.
def main() -> int:
    """Apply the Supabase database schema."""
    load_dotenv()
    db_url = os.getenv("SUPABASE_DB_URL")

    if not db_url:
        logger.error("Missing SUPABASE_DB_URL in .env")
        logger.info("Use the Supabase direct Postgres connection string, not the Project URL")
        return 1

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    try:
        apply_schema(db_url=db_url, schema_sql=schema_sql)
    except Exception as exc:
        logger.error("Failed to apply Supabase schema: {}", exc)
        return 1

    logger.info("Supabase schema applied successfully")
    return 0


# WHAT THIS DOES: Opens a Postgres connection and executes the local schema SQL.
# WHY THIS WAY: The script logic is easier to test when the actual connection work lives in one helper.
# SECURITY NOTE: The caller still supplies the DB URL from `.env`; this helper never logs the password.
def apply_schema(*, db_url: str, schema_sql: str) -> None:
    """Apply the schema SQL to a Postgres database."""
    with psycopg.connect(db_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema_sql)
        connection.commit()


if __name__ == "__main__":
    sys.exit(main())
