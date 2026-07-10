"""Tests for supported transcript file loading."""

from pathlib import Path

import pytest

from ingestion.transcript_loader import load_transcript


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_plain_text_transcript(tmp_path: Path) -> None:
    file_path = tmp_path / "meeting.txt"
    file_path.write_text(" Alice: Hello team. \n\n Bob: Hi Alice. ", encoding="utf-8")

    assert load_transcript(file_path) == "Alice: Hello team.\n\nBob: Hi Alice."


def test_load_webvtt_transcript_removes_metadata_and_timings(tmp_path: Path) -> None:
    file_path = tmp_path / "meeting.vtt"
    file_path.write_text(
        "\ufeffWEBVTT\n\n"
        "00:00:01.000 --> 00:00:04.000 align:start position:0%\n"
        "<v Alice>Let's approve the launch plan.</v>\n\n"
        "NOTE internal caption note\n"
        "this should not be loaded\n\n"
        "00:00:05.000 --> 00:00:08.000\n"
        "Bob: I will update the budget.\n",
        encoding="utf-8",
    )

    assert load_transcript(file_path) == (
        "Alice: Let's approve the launch plan.\n\n"
        "Bob: I will update the budget."
    )


def test_load_standard_distributed_dbms_vtt_fixture() -> None:
    file_path = FIXTURES_DIR / "distributed-dbms-meeting.vtt"

    loaded = load_transcript(file_path)

    assert "cue-1" not in loaded
    assert "00:00:03.215" not in loaded
    assert "Susan S. Caluya: So, at the end of this lesson," in loaded
    assert "Replication improves availability." in loaded


def test_load_edge_case_distributed_dbms_vtt_fixture() -> None:
    file_path = FIXTURES_DIR / "distributed-dbms-meeting-edge-cases.vtt"

    loaded = load_transcript(file_path)

    assert "WEBVTT" not in loaded
    assert "NOTE" not in loaded
    assert "empty-cue" not in loaded
    assert "align:start" not in loaded
    assert "Susan S. Caluya: So, at the end of this lesson," in loaded
    assert "Replication improves availability." in loaded


def test_load_srt_transcript_removes_sequence_numbers_and_timings(tmp_path: Path) -> None:
    file_path = tmp_path / "meeting.srt"
    file_path.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "Alice: Let's approve the launch plan.\n\n"
        "2\n"
        "00:00:05,000 --> 00:00:08,000\n"
        "Bob: I will update the budget.\n",
        encoding="utf-8",
    )

    assert load_transcript(file_path) == (
        "Alice: Let's approve the launch plan.\n\n"
        "Bob: I will update the budget."
    )


def test_rejects_unsupported_transcript_format(tmp_path: Path) -> None:
    file_path = tmp_path / "meeting.pdf"
    file_path.write_text("not a transcript", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported transcript format"):
        load_transcript(file_path)
