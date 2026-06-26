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
