"""Clean dirty transcript data before embedding."""

import re

from security.sanitize import sanitize_text, scrub_pii


BRACKET_TIMESTAMP_PATTERN = re.compile(r"\[?\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\b\]?")
SPEAKER_LABEL_PATTERN = re.compile(r"^\s*[A-Z][A-Za-z0-9 ._-]{0,40}:\s*")
FILLER_PATTERN = re.compile(r"\b(?:um+|uh+|erm|ah|like|you know)\b,?", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"[ \t]+")


# WHAT THIS DOES: Runs all transcript cleanup steps before chunking and embedding.
# WHY THIS MATTERS: Cleaner text creates better embeddings and avoids storing obvious private data.
def clean_transcript(text: str) -> str:
    """Remove transcript noise, sanitize markup, and mask PII."""
    cleaned = sanitize_text(text)
    cleaned = _remove_timestamps(cleaned)
    cleaned = _remove_speaker_labels(cleaned)
    cleaned = _remove_fillers(cleaned)
    cleaned = _normalize_whitespace(cleaned)
    return scrub_pii(cleaned)


# WHAT THIS DOES: Removes inline timestamps like [00:01:23] and 00:42.
# WHY THIS MATTERS: Timestamps usually hurt semantic search because they are not part of the meeting meaning.
def _remove_timestamps(text: str) -> str:
    """Remove common transcript timestamp fragments."""
    return BRACKET_TIMESTAMP_PATTERN.sub(" ", text)


# WHAT THIS DOES: Removes speaker prefixes such as "Alice:" at the start of each line.
# WHY THIS MATTERS: Phase 1 focuses on searchable meeting content, and names should not be embedded as PII.
def _remove_speaker_labels(text: str) -> str:
    """Remove simple speaker labels from transcript lines."""
    return "\n".join(SPEAKER_LABEL_PATTERN.sub("", line) for line in text.splitlines())


# WHAT THIS DOES: Removes common filler words from spoken transcripts.
# WHY THIS MATTERS: Fillers add noise and make chunks less focused for vector search.
def _remove_fillers(text: str) -> str:
    """Remove common spoken filler words."""
    return FILLER_PATTERN.sub(" ", text)


# WHAT THIS DOES: Collapses repeated spaces and blank lines into a stable plain-text shape.
# WHY THIS MATTERS: Predictable whitespace makes chunking and tests easier to reason about.
def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace while preserving paragraph breaks."""
    normalized_lines = [WHITESPACE_PATTERN.sub(" ", line).strip() for line in text.splitlines()]
    non_empty_lines = [line for line in normalized_lines if line]
    return "\n".join(non_empty_lines).strip()
