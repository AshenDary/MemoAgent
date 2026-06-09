"""Clean dirty transcript data before embedding."""

import re


def clean_transcript(text: str) -> str:
    """Normalize whitespace and remove obvious artifacts."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()
