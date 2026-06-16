"""Tests for transcript chunking and embedding record preparation."""

from ingestion.embedder import build_chunk_records, chunk_text, hash_filename


def test_chunk_text_splits_with_overlap() -> None:
    text = " ".join(f"word{i}" for i in range(120))

    chunks = chunk_text(text, chunk_size=50, chunk_overlap=10)

    assert len(chunks) > 1
    assert "word0" in chunks[0]
    assert "word119" in chunks[-1]


def test_build_chunk_records_validates_supabase_payload_shape() -> None:
    records = build_chunk_records(
        chunks=["Decision: ship the launch plan."],
        embeddings=[[0.1, 0.2, 0.3]],
        filename="weekly-sync.txt",
        workspace_id="workspace_123",
        metadata={"meeting_date": "2026-06-15"},
    )

    assert len(records) == 1
    assert records[0].filename == "weekly-sync.txt"
    assert records[0].filename_hash == hash_filename("weekly-sync.txt")
    assert records[0].metadata["source_filename"] == "weekly-sync.txt"
