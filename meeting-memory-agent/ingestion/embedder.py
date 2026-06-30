"""Chunk, embed, and store transcript segments."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

import google.generativeai as genai
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger
from pydantic import BaseModel, Field
from supabase import Client, create_client


DEFAULT_CHUNK_SIZE_TOKENS = 500
DEFAULT_CHUNK_OVERLAP_TOKENS = 50
DEFAULT_GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"
DEFAULT_EMBEDDING_DIMENSIONS = 768
TRANSCRIPT_CHUNKS_TABLE = "transcript_chunks"


# WHAT THIS DOES: Defines the exact shape of one chunk row before it is sent to Supabase.
# WHY THIS MATTERS: Pydantic catches bad data early, before malformed content reaches the vector DB.
class TranscriptChunk(BaseModel):
    """Validated row shape for storing transcript chunks."""

    workspace_id: str
    filename: str
    filename_hash: str
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


# WHAT THIS DOES: Breaks a cleaned transcript into smaller overlapping pieces.
# WHY THIS MATTERS: Embedding models work best on focused chunks, and overlap keeps context from being
# lost when an important sentence falls near a chunk boundary.
def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Split transcript text into overlapping chunks for embedding."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative")

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    cleaned_text = text.strip()
    if not cleaned_text:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=_approx_token_count,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [chunk.strip() for chunk in splitter.split_text(cleaned_text) if chunk.strip()]


# WHAT THIS DOES: Sends one text chunk to Gemini and gets back a fixed-size vector embedding.
# WHY THIS WAY: The model and dimensions are configurable, but default to the live-supported Gemini
# embedding model and the 768 dimensions declared in the Supabase pgvector schema.
# SECURITY NOTE: The API key is read from `.env`; transcript text is already sanitized before ingestion.
def embed_text(text: str, task_type: str = "retrieval_document") -> list[float]:
    """Embed text with the configured Gemini embedding model."""
    api_key = _required_env("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    model = _optional_env("GEMINI_EMBEDDING_MODEL", DEFAULT_GEMINI_EMBEDDING_MODEL)
    dimensions = _embedding_dimensions()

    try:
        response = genai.embed_content(
            model=model,
            content=text,
            task_type=task_type,
            output_dimensionality=dimensions,
        )
    except Exception as exc:
        logger.exception("Gemini embedding request failed")
        raise RuntimeError("Unable to create Gemini embedding") from exc

    embedding = response.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Gemini embedding response did not include an embedding")

    normalized_embedding = [float(value) for value in embedding]
    if len(normalized_embedding) != dimensions:
        raise RuntimeError(
            f"Gemini embedding returned {len(normalized_embedding)} dimensions; expected {dimensions}"
        )

    return normalized_embedding


# WHAT THIS DOES: Embeds every chunk from the transcript.
# WHY THIS MATTERS: Supabase stores one vector per chunk, so each chunk needs its own embedding.
def embed_chunks(chunks: Iterable[str]) -> list[list[float]]:
    """Embed a collection of transcript chunks."""
    return [embed_text(chunk) for chunk in chunks]


# WHAT THIS DOES: Combines chunks, embeddings, filename data, tenant/workspace ID, and metadata.
# WHY THIS MATTERS: This creates validated rows that are ready for insertion into Supabase.
def build_chunk_records(
    *,
    chunks: list[str],
    embeddings: list[list[float]],
    filename: str,
    workspace_id: str,
    metadata: dict[str, Any] | None = None,
) -> list[TranscriptChunk]:
    """Build validated Supabase rows for transcript chunks."""
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must have the same length")

    filename_hash = hash_filename(filename)
    base_metadata = metadata or {}

    return [
        TranscriptChunk(
            workspace_id=workspace_id,
            filename=filename,
            filename_hash=filename_hash,
            chunk_index=index,
            content=chunk,
            embedding=embedding,
            metadata={**base_metadata, "source_filename": filename},
        )
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]


# WHAT THIS DOES: Inserts prepared transcript chunk rows into Supabase.
# WHY THIS MATTERS: This is the persistence step that makes meeting memory searchable later.
def store_chunk_records(records: list[TranscriptChunk], client: Client | None = None) -> None:
    """Store embedded transcript chunks in Supabase."""
    if not records:
        logger.info("No transcript chunks to store")
        return

    supabase = client or get_supabase_client()
    payload = [_to_payload(record) for record in records]

    try:
        supabase.table(TRANSCRIPT_CHUNKS_TABLE).insert(payload).execute()
    except Exception as exc:
        logger.exception("Failed to store transcript chunks in Supabase")
        raise RuntimeError("Unable to store transcript chunks") from exc


# WHAT THIS DOES: Checks whether a filename has already been stored for a workspace.
# WHY THIS MATTERS: Deduplication prevents uploading the same meeting twice and wasting embedding/API cost.
def transcript_already_ingested(
    *,
    filename: str,
    workspace_id: str,
    client: Client | None = None,
) -> bool:
    """Return True when chunks for this workspace and filename hash already exist."""
    supabase = client or get_supabase_client()
    filename_hash = hash_filename(filename)

    try:
        response = (
            supabase.table(TRANSCRIPT_CHUNKS_TABLE)
            .select("filename_hash")
            .eq("workspace_id", workspace_id)
            .eq("filename_hash", filename_hash)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to check transcript deduplication status")
        raise RuntimeError("Unable to check transcript deduplication status") from exc

    return bool(response.data)


# WHAT THIS DOES: Runs the complete embedding pipeline for one transcript.
# WHY THIS MATTERS: This is the main function other code can call after loading and sanitizing a transcript.
def embed_and_store_transcript(
    *,
    text: str,
    filename: str | Path,
    workspace_id: str,
    metadata: dict[str, Any] | None = None,
    client: Client | None = None,
) -> list[TranscriptChunk]:
    """Chunk, embed, and store a transcript unless it was already ingested."""
    filename_text = Path(filename).name
    supabase = client or get_supabase_client()

    if transcript_already_ingested(
        filename=filename_text,
        workspace_id=workspace_id,
        client=supabase,
    ):
        logger.info("Skipping duplicate transcript: {}", filename_text)
        return []

    chunks = chunk_text(text)
    embeddings = embed_chunks(chunks)
    records = build_chunk_records(
        chunks=chunks,
        embeddings=embeddings,
        filename=filename_text,
        workspace_id=workspace_id,
        metadata=metadata,
    )
    store_chunk_records(records, client=supabase)
    return records


# WHAT THIS DOES: Creates the Supabase client using values from `.env`.
# WHY THIS MATTERS: Server-side ingestion should prefer a service-role key so RLS-protected writes work,
# while still allowing anon fallback for read-only or local setups.
def get_supabase_client() -> Client:
    """Create a Supabase client from environment variables."""
    url = _required_env("SUPABASE_URL")
    key = _optional_env("SUPABASE_SERVICE_ROLE_KEY", _required_env("SUPABASE_KEY"))
    return create_client(url, key)


# WHAT THIS DOES: Turns the filename into a stable SHA-256 hash.
# WHY THIS MATTERS: The hash is used for duplicate checks without relying only on raw filename comparisons.
def hash_filename(filename: str | Path) -> str:
    """Hash filenames for duplicate detection without storing raw lookup keys."""
    return hashlib.sha256(Path(filename).name.encode("utf-8")).hexdigest()


# WHAT THIS DOES: Loads `.env` and returns one required environment variable.
# WHY THIS MATTERS: Missing keys fail fast with a clear error instead of causing confusing API failures later.
def _required_env(name: str) -> str:
    """Read a required environment variable after loading local .env values."""
    load_dotenv()
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# WHAT THIS DOES: Reads an optional environment variable with a safe default.
# WHY THIS WAY: Model settings can change by environment without hardcoding project-specific values.
# SECURITY NOTE: This helper does not print env values, so secrets stay out of logs.
def _optional_env(name: str, default: str) -> str:
    """Read an optional environment variable after loading local .env values."""
    load_dotenv()
    return os.getenv(name, default)


# WHAT THIS DOES: Reads and validates the embedding dimension setting.
# WHY THIS WAY: Supabase pgvector columns require a fixed vector length, so bad config should fail early.
# SECURITY NOTE: The value is configuration, not user input, but validation still prevents unsafe surprises.
def _embedding_dimensions() -> int:
    """Return the configured embedding dimensions."""
    raw_value = _optional_env("GEMINI_EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS))
    try:
        dimensions = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("GEMINI_EMBEDDING_DIMENSIONS must be an integer") from exc

    if dimensions <= 0:
        raise RuntimeError("GEMINI_EMBEDDING_DIMENSIONS must be greater than zero")

    return dimensions


# WHAT THIS DOES: Estimates token count by counting words.
# WHY THIS MATTERS: It keeps chunking simple for now without adding a tokenizer dependency during Phase 1.
def _approx_token_count(text: str) -> int:
    """Approximate token count without adding another tokenizer dependency."""
    return max(1, len(text.split()))


# WHAT THIS DOES: Converts a Pydantic model into a plain dictionary.
# WHY THIS MATTERS: Pydantic v1 uses `.dict()`, while Pydantic v2 uses `.model_dump()`.
def _to_payload(record: TranscriptChunk) -> dict[str, Any]:
    """Serialize pydantic models across supported pydantic versions."""
    if hasattr(record, "model_dump"):
        return record.model_dump()

    return record.dict()
