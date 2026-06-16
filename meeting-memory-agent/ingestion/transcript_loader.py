"""Load and normalize raw transcript files for downstream processing."""

from __future__ import annotations

from pathlib import Path


ALLOWED_TRANSCRIPT_EXTENSIONS = {".txt", ".vtt", ".srt"}
MAX_TRANSCRIPT_BYTES = 10 * 1024 * 1024


def load_transcript(file_path: str | Path) -> str:
    """Read a supported transcript file and return normalized transcript text."""
    path = _validate_transcript_path(file_path)
    raw_text = path.read_text(encoding="utf-8-sig")

    if path.suffix.lower() == ".vtt":
        return _parse_vtt(raw_text)

    if path.suffix.lower() == ".srt":
        return _parse_srt(raw_text)

    return _normalize_lines(raw_text.splitlines())


# WHAT THIS DOES: Confirms the transcript exists, is text-like, and stays under the upload size limit.
# WHY THIS WAY: Validating before reading prevents accidental binary reads and oversized memory use.
# SECURITY NOTE: Uploaded transcript files are untrusted input, so extension and size checks happen first.
def _validate_transcript_path(file_path: str | Path) -> Path:
    """Validate the transcript path before reading file contents."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Transcript file does not exist: {path}")

    if not path.is_file():
        raise ValueError(f"Transcript path must point to a file: {path}")

    if path.suffix.lower() not in ALLOWED_TRANSCRIPT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_TRANSCRIPT_EXTENSIONS))
        raise ValueError(f"Unsupported transcript format '{path.suffix}'. Allowed: {allowed}")

    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("Transcript file exceeds the 10MB upload limit")

    return path


# WHAT THIS DOES: Removes WebVTT metadata and cue timings while preserving spoken text.
# WHY THIS WAY: VTT files mix transcript content with player timing data that should not be embedded.
# SECURITY NOTE: This is format cleanup only; PII masking and XSS cleaning happen in the sanitizer step.
def _parse_vtt(raw_text: str) -> str:
    """Parse WebVTT transcript content into plain text."""
    lines = raw_text.splitlines()
    cleaned_lines: list[str] = []
    skip_block = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            skip_block = False
            cleaned_lines.append("")
            continue

        upper = stripped.upper()
        if upper == "WEBVTT" or upper.startswith(("WEBVTT ", "KIND:", "LANGUAGE:")):
            continue

        if upper.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue

        if skip_block or _is_timestamp_line(stripped):
            continue

        cleaned_lines.append(_remove_vtt_voice_tag(stripped))

    return _normalize_lines(cleaned_lines)


# WHAT THIS DOES: Removes SRT cue numbers and timings while keeping the words people said.
# WHY THIS WAY: SRT sequence numbers and time ranges add noise to embeddings.
# SECURITY NOTE: The returned text is still untrusted and must pass through sanitizer.py next.
def _parse_srt(raw_text: str) -> str:
    """Parse SubRip transcript content into plain text."""
    cleaned_lines: list[str] = []

    for line in raw_text.splitlines():
        stripped = line.strip()

        if not stripped:
            cleaned_lines.append("")
            continue

        if stripped.isdigit() or _is_timestamp_line(stripped):
            continue

        cleaned_lines.append(stripped)

    return _normalize_lines(cleaned_lines)


# WHAT THIS DOES: Detects common VTT/SRT cue timing lines.
# WHY THIS WAY: Both formats use arrow-separated timestamp ranges with optional cue settings.
# SECURITY NOTE: This avoids storing playback metadata in the vector database.
def _is_timestamp_line(line: str) -> bool:
    """Return True when a line looks like a VTT or SRT timestamp cue."""
    return "-->" in line and any(char.isdigit() for char in line)


# WHAT THIS DOES: Converts WebVTT voice tags into readable speaker labels.
# WHY THIS WAY: Zoom and other tools can encode speakers as <v Name>spoken text</v>.
# SECURITY NOTE: This is not HTML sanitization; sanitizer.py still strips unsafe markup later.
def _remove_vtt_voice_tag(line: str) -> str:
    """Replace a WebVTT voice tag with a simple speaker label."""
    if line.startswith("<v ") and ">" in line:
        speaker, text = line[3:].split(">", maxsplit=1)
        return f"{speaker.strip()}: {text.replace('</v>', '').strip()}"

    return line.replace("</v>", "")


# WHAT THIS DOES: Collapses duplicate blank lines and trims whitespace.
# WHY THIS WAY: A stable text shape makes sanitizer tests and chunking more predictable.
# SECURITY NOTE: Normalization is not a substitute for content sanitization.
def _normalize_lines(lines: list[str]) -> str:
    """Normalize transcript lines into readable plain text."""
    normalized: list[str] = []
    previous_blank = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if normalized and not previous_blank:
                normalized.append("")
            previous_blank = True
            continue

        normalized.append(stripped)
        previous_blank = False

    return "\n".join(normalized).strip()
