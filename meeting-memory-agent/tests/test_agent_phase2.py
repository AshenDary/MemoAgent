"""Tests for the Phase 2 graph and agent tool wrappers."""

from __future__ import annotations

from typing import Any

import agent.graph as graph_module
import agent.tools as tools_module
from agent.graph import build_graph
from agent.tools import answer_from_memory, list_tools, search_transcripts
from retrieval.retriever import RAGAnswer


def test_build_graph_invokes_rag_answer_node(monkeypatch: Any) -> None:
    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        return RAGAnswer(
            question=question,
            answer=f"Answered for {workspace_id} with k={top_k}",
            citations=["weekly-sync.txt#0"],
            chunks=[],
        )

    monkeypatch.setattr(graph_module, "answer_question", fake_answer_question)

    graph = build_graph()
    result = graph.invoke(
        {
            "question": "What did we decide?",
            "workspace_id": "workspace_123",
            "top_k": 3,
        }
    )

    assert result["answer"] == "Answered for workspace_123 with k=3"
    assert result["citations"] == ["weekly-sync.txt#0"]
    assert result["chunks"] == []


def test_list_tools_returns_phase2_tools() -> None:
    assert list_tools() == ["search_transcripts", "answer_from_memory"]


def test_search_transcripts_wraps_search_memories(monkeypatch: Any) -> None:
    def fake_search_memories(
        *,
        query: str,
        workspace_id: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return [{"query": query, "workspace_id": workspace_id, "top_k": top_k}]

    monkeypatch.setattr(tools_module, "search_memories", fake_search_memories)

    results = search_transcripts(
        query="launch plan",
        workspace_id="workspace_123",
        top_k=2,
    )

    assert results == [{"query": "launch plan", "workspace_id": "workspace_123", "top_k": 2}]


def test_answer_from_memory_wraps_rag_answer(monkeypatch: Any) -> None:
    def fake_answer_question(*, question: str, workspace_id: str, top_k: int) -> RAGAnswer:
        return RAGAnswer(
            question=question,
            answer="The launch plan was approved.",
            citations=["weekly-sync.txt#0"],
            chunks=[],
        )

    monkeypatch.setattr(tools_module, "answer_question", fake_answer_question)

    result = answer_from_memory(
        question="Was the launch plan approved?",
        workspace_id="workspace_123",
    )

    assert result["answer"] == "The launch plan was approved."
    assert result["citations"] == ["weekly-sync.txt#0"]
