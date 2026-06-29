"""Tests for the Phase 2 FastAPI query endpoint."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app
from retrieval.retriever import MeetingSummary, RAGAnswer, RetrievedChunk


client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_endpoint_returns_rag_answer(monkeypatch: Any) -> None:
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
    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        raise RuntimeError("database password leaked here would be bad")

    monkeypatch.setattr(api_main, "answer_question", fake_answer_question)

    response = client.post(
        "/query",
        json={
            "workspace_id": "workspace_123",
            "question": "Was the launch approved?",
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to answer query"}


def test_query_endpoint_validates_top_k_limit() -> None:
    response = client.post(
        "/query",
        json={
            "workspace_id": "workspace_123",
            "question": "Was the launch approved?",
            "top_k": 100,
        },
    )

    assert response.status_code == 422


def test_get_meetings_endpoint_returns_meeting_summaries(monkeypatch: Any) -> None:
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

    response = client.get("/meetings", params={"workspace_id": "workspace_123"})

    body = response.json()
    assert response.status_code == 200
    assert body["workspace_id"] == "workspace_123"
    assert body["meetings"][0]["filename"] == "weekly-sync.txt"
    assert body["meetings"][0]["chunk_count"] == 4


def test_agent_query_endpoint_returns_routed_response(monkeypatch: Any) -> None:
    api_main._AGENT_SESSIONS.clear()

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
        json={
            "workspace_id": "workspace_123",
            "session_id": "session_123",
            "message": "First question",
        },
    )
    second = client.post(
        "/agent/query",
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

    class FakeAgentGraph:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Tool call limit reached for this session")

    monkeypatch.setattr(api_main, "_AGENT_GRAPH", FakeAgentGraph())

    response = client.post(
        "/agent/query",
        json={
            "workspace_id": "workspace_123",
            "session_id": "session_123",
            "message": "Find action items",
        },
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Tool call limit reached for this session"}
