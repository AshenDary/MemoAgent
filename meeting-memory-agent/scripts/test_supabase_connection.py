"""Test Supabase connectivity without printing secret values."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.embedder import get_supabase_client


# WHAT THIS DOES: Creates a Supabase REST client and makes a tiny request.
# WHY THIS MATTERS: It confirms SUPABASE_URL and SUPABASE_KEY are usable by the codebase.
def main() -> int:
    """Run a safe Supabase connection check."""
    load_dotenv()

    try:
        client = get_supabase_client()
        client.table("transcript_chunks").select("id").limit(1).execute()
    except Exception as exc:
        logger.error("Supabase connection check failed: {}", exc)
        return 1

    logger.info("Supabase connection check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
