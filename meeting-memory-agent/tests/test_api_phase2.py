"""Tests for the Phase 2 FastAPI query endpoint."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app
from security.auth import StoredAPIKey
from security.rate_limit import RateLimiter
from security.stores import InMemoryAPIKeyStore, InMemoryAgentSessionStore, InMemoryAuditLogStore
from ingestion.embedder import TranscriptChunk
from ingestion.transcript_loader import load_transcript
from retrieval.retriever import MeetingSummary, RAGAnswer, RetrievedChunk


client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _use_in_memory_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force in-memory security stores for all tests."""
    monkeypatch.setenv("USE_IN_MEMORY_SECURITY_STORE", "1")
    in_mem_api_key = InMemoryAPIKeyStore()
    in_mem_session = InMemoryAgentSessionStore()
    in_mem_audit = InMemoryAuditLogStore()
    monkeypatch.setattr(api_main, "_API_KEY_STORE", in_mem_api_key)
    monkeypatch.setattr(api_main, "_AGENT_SESSION_STORE", in_mem_session)
    monkeypatch.setattr(api_main, "_AUDIT_LOG_STORE", in_mem_audit)
    monkeypatch.setattr(api_main, "_AGENT_SESSIONS", in_mem_session)
    api_main._RATE_LIMITER.reset()


def _create_test_api_key(workspace_id: str = "workspace_123") -> str:
    api_main._API_KEY_STORE.clear()
    response = client.post("/auth/create-key", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    return str(response.json()["api_key"])


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_is_not_wildcard_by_default() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") is None


def test_query_endpoint_returns_rag_answer(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()

    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        return RAGAnswer(
            question=question,
            answer="The launch plan was approved [source:weekly-sync.txt:chunk:0].",
            citations=["source:weekly-sync.txt:chunk:0"],
            chunks=[
                RetrievedChunk(
                    workspace_id=workspace_id,
                    filename="weekly-sync.txt",
                    chunk_index=0,
                    content="The launch plan was approved.",
                    similarity=0.91,
                )
            ],
        )

    monkeypatch.setattr(api_main, "answer_question", fake_answer_question)

    response = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "question": "<b>Was the launch approved?</b>",
            "top_k": 3,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["question"] == "Was the launch approved?"
    assert body["answer"] == "The launch plan was approved."
    assert body["citations"] == ["source:weekly-sync.txt:chunk:0"]
    assert body["chunks"][0]["filename"] == "weekly-sync.txt"


def test_query_endpoint_sanitizes_xss_input(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()
    captured: dict[str, Any] = {}

    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        captured["question"] = question
        return RAGAnswer(
            question=question,
            answer="ok",
            citations=[],
            chunks=[],
        )

    monkeypatch.setattr(api_main, "answer_question", fake_answer_question)

    response = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "question": "<script>alert('xss')</script> What was approved?",
        },
    )

    assert response.status_code == 200
    assert "<script>" not in str(captured["question"])
    assert "What was approved?" in str(captured["question"])


def test_query_endpoint_hides_internal_errors(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()

    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        raise RuntimeError("database password leaked here would be bad")

    monkeypatch.setattr(api_main, "answer_question", fake_answer_question)

    response = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "question": "Was the launch approved?",
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to answer query"}


def test_query_endpoint_validates_top_k_limit() -> None:
    api_key = _create_test_api_key()

    response = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "question": "Was the launch approved?",
            "top_k": 100,
        },
    )

    assert response.status_code == 422


def test_query_endpoint_returns_429_when_rate_limited(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()

    monkeypatch.setattr(api_main, "_RATE_LIMITER", RateLimiter(max_requests=1, window_seconds=60))

    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        return RAGAnswer(question=question, answer="ok", citations=[], chunks=[])

    monkeypatch.setattr(api_main, "answer_question", fake_answer_question)

    first = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "question": "Was the launch approved?",
        },
    )
    second = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "question": "Was the launch approved again?",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {"detail": "Rate limit exceeded. Please try again later."}
    assert second.headers.get("retry-after") is not None


def test_get_meetings_endpoint_returns_meeting_summaries(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()

    def fake_list_meetings(*, workspace_id: str) -> list[MeetingSummary]:
        return [
            MeetingSummary(
                workspace_id=workspace_id,
                filename="weekly-sync.txt",
                filename_hash="abc123",
                meeting_date="2026-06-15",
                chunk_count=4,
                latest_created_at="2026-06-15T12:00:00Z",
            )
        ]

    monkeypatch.setattr(api_main, "list_meetings", fake_list_meetings)

    response = client.get(
        "/meetings",
        headers={"X-API-Key": api_key},
        params={"workspace_id": "workspace_123"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["workspace_id"] == "workspace_123"
    assert body["meetings"][0]["filename"] == "weekly-sync.txt"
    assert body["meetings"][0]["chunk_count"] == 4


def test_agent_query_endpoint_returns_routed_response(monkeypatch: Any) -> None:
    api_main._AGENT_SESSIONS.clear()
    api_key = _create_test_api_key()

    class FakeAgentGraph:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                **state,
                "selected_tool": "find_action_items",
                "answer": "Dana will send the launch checklist",
                "citations": ["source:weekly-sync.txt:chunk:2"],
                "chunks": [],
                "tool_call_count": state["tool_call_count"] + 1,
                "conversation_history": [*state["conversation_history"], state["question"]],
            }

    monkeypatch.setattr(api_main, "_AGENT_GRAPH", FakeAgentGraph())

    response = client.post(
        "/agent/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "session_id": "session_123",
            "message": "<b>What action items are open?</b>",
            "top_k": 3,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["selected_tool"] == "find_action_items"
    assert body["answer"] == "Dana will send the launch checklist"
    assert body["tool_call_count"] == 1
    assert body["conversation_history"] == ["What action items are open?"]


def test_agent_query_endpoint_preserves_session_state(monkeypatch: Any) -> None:
    api_main._AGENT_SESSIONS.clear()
    api_key = _create_test_api_key()

    class FakeAgentGraph:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            return {
                **state,
                "selected_tool": "answer_from_memory",
                "answer": "ok",
                "citations": [],
                "chunks": [],
                "tool_call_count": state["tool_call_count"] + 1,
                "conversation_history": [*state["conversation_history"], state["question"]],
            }

    monkeypatch.setattr(api_main, "_AGENT_GRAPH", FakeAgentGraph())

    first = client.post(
        "/agent/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "session_id": "session_123",
            "message": "First question",
        },
    )
    second = client.post(
        "/agent/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "session_id": "session_123",
            "message": "Second question",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["tool_call_count"] == 2
    assert second.json()["conversation_history"] == ["First question", "Second question"]


def test_agent_query_endpoint_returns_429_for_tool_limit(monkeypatch: Any) -> None:
    api_main._AGENT_SESSIONS.clear()
    api_key = _create_test_api_key()

    class FakeAgentGraph:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Tool call limit reached for this session")

    monkeypatch.setattr(api_main, "_AGENT_GRAPH", FakeAgentGraph())

    response = client.post(
        "/agent/query",
        headers={"X-API-Key": api_key},
        json={
            "workspace_id": "workspace_123",
            "session_id": "session_123",
            "message": "Find action items",
        },
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Tool call limit reached for this session"}


def test_create_key_returns_plaintext_once_and_stores_hash() -> None:
    api_main._API_KEY_STORE.clear()

    response = client.post("/auth/create-key", json={"workspace_id": "workspace_123"})

    body = response.json()
    assert response.status_code == 200
    assert body["api_key"].startswith("mma_")
    stored = api_main._API_KEY_STORE.records[body["key_id"]]
    assert stored.workspace_id == "workspace_123"
    assert stored.key_hash != body["api_key"]


def test_protected_endpoint_rejects_missing_api_key() -> None:
    api_main._API_KEY_STORE.clear()

    response = client.get("/meetings", params={"workspace_id": "workspace_123"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing API key"}


def test_protected_endpoint_rejects_malformed_api_key() -> None:
    _create_test_api_key()

    response = client.get(
        "/meetings",
        headers={"X-API-Key": "not-a-real-key"},
        params={"workspace_id": "workspace_123"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid API key for workspace"}


def test_protected_endpoint_rejects_revoked_api_key() -> None:
    api_key = _create_test_api_key()
    key_id = next(iter(api_main._API_KEY_STORE.records))
    stored = api_main._API_KEY_STORE.records[key_id]
    api_main._API_KEY_STORE.records[key_id] = StoredAPIKey(
        key_id=stored.key_id,
        workspace_id=stored.workspace_id,
        key_hash=stored.key_hash,
        revoked_at="2026-01-01T00:00:00Z",
    )

    response = client.get(
        "/meetings",
        headers={"X-API-Key": api_key},
        params={"workspace_id": "workspace_123"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid API key for workspace"}


def test_protected_endpoint_rejects_cross_workspace_key() -> None:
    api_key = _create_test_api_key(workspace_id="workspace_a")

    response = client.get(
        "/meetings",
        headers={"X-API-Key": api_key},
        params={"workspace_id": "workspace_b"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid API key for workspace"}


def test_upload_endpoint_validates_and_ingests_transcript(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()
    calls: list[dict[str, Any]] = []

    def fake_ingest_transcript_file(
        *,
        file_path: str,
        workspace_id: str,
        metadata: dict[str, Any],
        source_filename: str,
    ) -> list[TranscriptChunk]:
        calls.append(
            {
                "file_path": file_path,
                "workspace_id": workspace_id,
                "metadata": metadata,
                "source_filename": source_filename,
            }
        )
        return [
            TranscriptChunk(
                workspace_id=workspace_id,
                filename=source_filename,
                filename_hash="hash",
                chunk_index=0,
                content="Launch approved.",
                embedding=[0.1, 0.2, 0.3],
            )
        ]

    monkeypatch.setattr(api_main, "ingest_transcript_file", fake_ingest_transcript_file)

    response = client.post(
        "/upload",
        headers={"X-API-Key": api_key},
        data={"workspace_id": "workspace_123", "meeting_date": "2026-06-29"},
        files={"file": ("weekly-sync.txt", b"Alice: Launch approved.", "text/plain")},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["filename"] == "weekly-sync.txt"
    assert body["chunks_stored"] == 1
    assert calls[0]["source_filename"] == "weekly-sync.txt"
    assert calls[0]["metadata"] == {"meeting_date": "2026-06-29"}


@pytest.mark.parametrize(
    ("fixture_name", "upload_filename", "content_type"),
    [
        ("distributed-dbms-meeting.vtt", "distributed DBMS.vtt", "text/vtt"),
        ("distributed-dbms-meeting-edge-cases.vtt", "distributed DBMS.vtt", "application/octet-stream"),
    ],
)
def test_upload_endpoint_accepts_real_world_vtt_variants(
    fixture_name: str,
    upload_filename: str,
    content_type: str,
    monkeypatch: Any,
) -> None:
    api_key = _create_test_api_key()
    parsed_texts: list[str] = []

    def fake_ingest_transcript_file(
        *,
        file_path: str,
        workspace_id: str,
        metadata: dict[str, Any],
        source_filename: str,
    ) -> list[TranscriptChunk]:
        parsed_text = load_transcript(file_path)
        parsed_texts.append(parsed_text)
        return [
            TranscriptChunk(
                workspace_id=workspace_id,
                filename=source_filename,
                filename_hash="hash",
                chunk_index=0,
                content=parsed_text,
                embedding=[0.1, 0.2, 0.3],
            )
        ]

    monkeypatch.setattr(api_main, "ingest_transcript_file", fake_ingest_transcript_file)
    fixture_bytes = (FIXTURES_DIR / fixture_name).read_bytes()

    response = client.post(
        "/upload",
        headers={"X-API-Key": api_key},
        data={"workspace_id": "workspace_123"},
        files={"file": (upload_filename, fixture_bytes, content_type)},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == upload_filename
    assert "cue-1" not in parsed_texts[0]
    assert "align:start" not in parsed_texts[0]
    assert "Replication improves availability." in parsed_texts[0]


def test_upload_metadata_accepts_blank_vtt_mime_type() -> None:
    class BlankMimeUpload:
        filename = "distributed DBMS.vtt"
        content_type = ""

    assert api_main._validate_upload_metadata(BlankMimeUpload()) == "distributed DBMS.vtt"  # type: ignore[arg-type]


def test_upload_endpoint_returns_specific_embedding_error(monkeypatch: Any) -> None:
    api_key = _create_test_api_key()

    def fake_ingest_transcript_file(
        *,
        file_path: str,
        workspace_id: str,
        metadata: dict[str, Any],
        source_filename: str,
    ) -> list[TranscriptChunk]:
        raise RuntimeError("Unable to create Gemini embedding")

    monkeypatch.setattr(api_main, "ingest_transcript_file", fake_ingest_transcript_file)

    response = client.post(
        "/upload",
        headers={"X-API-Key": api_key},
        data={"workspace_id": "workspace_123"},
        files={"file": ("distributed DBMS.vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello", "text/vtt")},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Unable to create transcript embeddings"}


def test_upload_endpoint_rejects_bad_mime_type() -> None:
    api_key = _create_test_api_key()

    response = client.post(
        "/upload",
        headers={"X-API-Key": api_key},
        data={"workspace_id": "workspace_123"},
        files={"file": ("weekly-sync.txt", b"hello", "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported transcript MIME type"}


def test_upload_endpoint_rejects_oversized_file() -> None:
    api_key = _create_test_api_key()

    response = client.post(
        "/upload",
        headers={"X-API-Key": api_key},
        data={"workspace_id": "workspace_123"},
        files={"file": ("weekly-sync.txt", b"a" * (10 * 1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Transcript file exceeds the 10MB upload limit"}
