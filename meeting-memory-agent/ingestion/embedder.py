"""Chunk, embed, and store transcript segments."""

from typing import Iterable


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Naive character-based chunking."""
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def embed_chunks(chunks: Iterable[str]) -> list[list[float]]:
    """Placeholder embedding function."""
    return [[0.0] * 8 for _ in chunks]
