"""Security-focused tests for transcript sanitization."""

from ingestion.sanitizer import clean_transcript
from security.sanitize import sanitize_text, scrub_pii


def test_scrub_pii_redacts_email() -> None:
    text = "Reach me at alice@example.com"
    assert "alice@example.com" not in scrub_pii(text)


def test_scrub_pii_redacts_phone_number() -> None:
    text = "Call me at +1 (415) 555-1212 after the meeting."

    scrubbed = scrub_pii(text)

    assert "415" not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed


def test_sanitize_text_strips_html() -> None:
    text = "<script>alert('xss')</script><b>Launch approved</b>"

    sanitized = sanitize_text(text)

    assert "<script>" not in sanitized
    assert "<b>" not in sanitized
    assert "Launch approved" in sanitized


def test_clean_transcript_removes_noise_and_masks_pii() -> None:
    text = """
    [00:01:23] Alice: Um, we should approve the launch plan.
    Bob: you know, email me at bob@example.com or call 415-555-1212.
    """

    cleaned = clean_transcript(text)

    assert "00:01:23" not in cleaned
    assert "Alice:" not in cleaned
    assert "Bob:" not in cleaned
    assert "Um" not in cleaned
    assert "you know" not in cleaned
    assert "bob@example.com" not in cleaned
    assert "415-555-1212" not in cleaned
    assert "[REDACTED_EMAIL]" in cleaned
    assert "[REDACTED_PHONE]" in cleaned


def test_clean_transcript_strips_xss_markup() -> None:
    text = "<script>alert('xss')</script> <img src=x onerror=alert(1)> Alice: Launch approved."

    cleaned = clean_transcript(text)

    assert "<script>" not in cleaned
    assert "</script>" not in cleaned
    assert "<img" not in cleaned
    assert "Launch approved" in cleaned
