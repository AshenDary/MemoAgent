"""Tests for the Phase 2 FastAPI query endpoint."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app
from ingestion.embedder import TranscriptChunk
from retrieval.retriever import MeetingSummary, RAGAnswer, RetrievedChunk


client = TestClient(app)


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
            answer="The launch plan was approved [weekly-sync.txt#0].",
            citations=["weekly-sync.txt#0"],
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
    assert body["citations"] == ["weekly-sync.txt#0"]
    assert body["chunks"][0]["filename"] == "weekly-sync.txt"


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
    stored = api_main._API_KEY_STORE[body["key_id"]]
    assert stored.workspace_id == "workspace_123"
    assert stored.key_hash != body["api_key"]


def test_protected_endpoint_rejects_missing_api_key() -> None:
    api_main._API_KEY_STORE.clear()

    response = client.get("/meetings", params={"workspace_id": "workspace_123"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing API key"}


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
