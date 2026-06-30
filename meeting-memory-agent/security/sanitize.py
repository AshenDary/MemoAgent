"""Input validation and PII scrubbing helpers."""

from __future__ import annotations

import re
from functools import lru_cache

import bleach
from loguru import logger


ALLOWED_TEXT_TAGS: set[str] = set()
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(
    r"""
    (?<!\w)
    (?:\+?\d{1,3}[\s.-]?)?
    (?:\(?\d{3}\)?[\s.-]?)?
    \d{3}[\s.-]?\d{4}
    (?!\w)
    """,
    re.VERBOSE,
)


# WHAT THIS DOES: Removes HTML/script markup from untrusted text.
# WHY THIS MATTERS: Transcript and query text can come from uploads/users, so we strip markup before use.
def sanitize_text(text: str) -> str:
    """Strip HTML and script content from external text."""
    return bleach.clean(text, tags=ALLOWED_TEXT_TAGS, attributes={}, strip=True)


# WHAT THIS DOES: Redacts emails, phone numbers, and detected person names.
# WHY THIS MATTERS: Meeting transcripts often contain private data that should not be embedded or sent to LLMs.
def scrub_pii(text: str) -> str:
    """Replace common PII with redaction markers."""
    scrubbed = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    scrubbed = PHONE_PATTERN.sub("[REDACTED_PHONE]", scrubbed)
    return _scrub_names(scrubbed)


# WHAT THIS DOES: Uses spaCy NER to replace detected person names.
# WHY THIS MATTERS: Regex works for emails/phones, but names need entity recognition.
def _scrub_names(text: str) -> str:
    """Replace spaCy PERSON entities when the local model is installed."""
    nlp = _load_spacy_model()
    if nlp is None:
        logger.warning("spaCy model unavailable; skipping PERSON name redaction")
        return text

    doc = nlp(text)
    scrubbed = text
    for entity in reversed(doc.ents):
        if entity.label_ == "PERSON":
            scrubbed = f"{scrubbed[: entity.start_char]}[REDACTED_NAME]{scrubbed[entity.end_char :]}"

    return scrubbed


# WHAT THIS DOES: Loads the spaCy English model once and caches it.
# WHY THIS MATTERS: Loading the model is expensive, so repeated transcript cleanup should reuse it.
@lru_cache(maxsize=1)
def _load_spacy_model() -> object | None:
    """Load spaCy's small English model if it is available."""
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except (ModuleNotFoundError, OSError):
        return None
