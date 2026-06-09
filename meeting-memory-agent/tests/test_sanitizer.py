"""Security-focused tests for transcript sanitization."""

from security.sanitize import scrub_pii


def test_scrub_pii_redacts_email() -> None:
    text = "Reach me at alice@example.com"
    assert "alice@example.com" not in scrub_pii(text)
