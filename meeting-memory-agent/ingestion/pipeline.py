"""Phase 1 ingestion pipeline for transcript files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ingestion.embedder import TranscriptChunk, embed_and_store_transcript
from ingestion.sanitizer import clean_transcript
from ingestion.transcript_loader import load_transcript


# WHAT THIS DOES: Loads a transcript file, cleans it, embeds it, and stores the chunks.
# WHY THIS MATTERS: This is the Phase 1 end-to-end path from raw transcript to vector database.
def ingest_transcript_file(
    *,
    file_path: str | Path,
    workspace_id: str,
    metadata: dict[str, Any] | None = None,
) -> list[TranscriptChunk]:
    """Ingest one transcript file into Supabase pgvector storage."""
    path = Path(file_path)
    raw_text = load_transcript(path)
    cleaned_text = clean_transcript(raw_text)

    return embed_and_store_transcript(
        text=cleaned_text,
        filename=path.name,
        workspace_id=workspace_id,
        metadata=metadata,
    )
