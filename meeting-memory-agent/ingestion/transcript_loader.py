"""Load raw transcript files for downstream processing."""

from pathlib import Path


def load_transcript(file_path: str) -> str:
    """Read and return transcript text from disk."""
    return Path(file_path).read_text(encoding="utf-8")
