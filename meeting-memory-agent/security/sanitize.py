"""Input validation and PII scrubbing helpers."""

import re


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def scrub_pii(text: str) -> str:
    """Replace emails with a redaction marker."""
    return EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
