"""Run a live end-to-end ingestion and RAG check against Supabase/Gemini/Groq."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.embedder import get_supabase_client, hash_filename
from ingestion.pipeline import ingest_transcript_file
from retrieval.retriever import answer_question


DEFAULT_WORKSPACE_ID = "live_rag_check_workspace"
DEFAULT_QUESTION = "What did the team decide about the launch plan?"


# WHAT THIS DOES: Runs a synthetic transcript through ingest, retrieval, and answer generation.
# WHY THIS WAY: A generated transcript proves the live pipeline works without exposing real meeting data.
# SECURITY NOTE: The script never prints secrets and can delete the test rows after verification.
def main() -> int:
    """Run the live RAG check from the command line."""
    load_dotenv()
    args = _parse_args()
    filename = _unique_filename()

    try:
        transcript_path = _write_sample_transcript(filename)
        records = ingest_transcript_file(
            file_path=transcript_path,
            workspace_id=args.workspace_id,
            metadata={"meeting_date": "2026-06-22", "source": "live_rag_check"},
        )
        logger.info("Ingested {} chunk(s) for {}", len(records), filename)

        result = answer_question(
            question=args.question,
            workspace_id=args.workspace_id,
            top_k=args.top_k,
        )
        logger.info("Answer: {}", result.answer)
        logger.info("Citations: {}", ", ".join(result.citations) or "none")

        if not args.keep_data:
            _delete_test_rows(filename=filename, workspace_id=args.workspace_id)
            logger.info("Deleted live-check rows for {}", filename)
    except Exception as exc:
        logger.error("Live RAG check failed: {}", exc)
        logger.info("Confirm the Supabase schema is applied and SUPABASE_KEY can access transcript_chunks")
        return 1
    finally:
        if "transcript_path" in locals():
            transcript_path.unlink(missing_ok=True)

    return 0


# WHAT THIS DOES: Defines CLI flags for workspace, question, top-k, and cleanup behavior.
# WHY THIS WAY: You can rerun the same check against different tenants or retrieval sizes.
# SECURITY NOTE: User-provided question text still goes through the normal RAG sanitization path.
def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run a live Meeting Memory RAG check.")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--keep-data", action="store_true")
    return parser.parse_args()


# WHAT THIS DOES: Creates a unique filename so deduplication does not skip the live check.
# WHY THIS WAY: The ingest pipeline deduplicates by filename hash per workspace.
# SECURITY NOTE: The filename contains no user or secret data.
def _unique_filename() -> str:
    """Return a unique transcript filename for this run."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"live-rag-check-{timestamp}.txt"


# WHAT THIS DOES: Writes a small synthetic meeting transcript to a temporary file.
# WHY THIS WAY: Using tempfile avoids committing or keeping raw transcript data in the repo.
# SECURITY NOTE: The sample includes fake PII so the sanitizer path is exercised safely.
def _write_sample_transcript(filename: str) -> Path:
    """Create a temporary transcript file for ingestion."""
    temp_dir = Path(tempfile.mkdtemp(prefix="memoagent-live-rag-"))
    transcript_path = temp_dir / filename
    transcript_path.write_text(
        "\n".join(
            [
                "[00:00:01] Alice: Um, the team approved the launch plan for Friday.",
                "Bob: Sarah will prepare the customer announcement by Thursday.",
                "Carol: Email carol@example.com if the budget changes.",
            ]
        ),
        encoding="utf-8",
    )
    return transcript_path


# WHAT THIS DOES: Removes rows inserted by this live check.
# WHY THIS WAY: Keeping the database clean prevents test data from polluting future retrieval results.
# SECURITY NOTE: Delete is scoped by workspace_id and filename_hash, so it cannot wipe other meetings.
def _delete_test_rows(*, filename: str, workspace_id: str) -> None:
    """Delete live-check rows from Supabase."""
    client = get_supabase_client()
    filename_hash = hash_filename(filename)
    client.table("transcript_chunks").delete().eq("workspace_id", workspace_id).eq(
        "filename_hash", filename_hash
    ).execute()


if __name__ == "__main__":
    sys.exit(main())
