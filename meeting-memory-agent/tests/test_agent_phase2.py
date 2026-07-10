"""Tests for the Phase 2 graph and agent tool wrappers."""

from __future__ import annotations

from typing import Any

import agent.graph as graph_module
import agent.tools as tools_module
from agent.graph import build_graph
from agent.tools import (
    AgentSession,
    answer_from_memory,
    find_action_items,
    list_tools,
    search_transcripts,
)
from retrieval.retriever import RAGAnswer


def test_build_graph_routes_default_questions_to_rag_tool(monkeypatch: Any) -> None:
    def fake_answer_from_memory(
        *,
        question: str,
        workspace_id: str,
        top_k: int,
        session: AgentSession,
    ) -> dict[str, Any]:
        session.tool_call_count += 1
        return {
            "question": question,
            "answer": f"Answered for {workspace_id} with k={top_k} [source:weekly-sync.txt:chunk:0]",
            "citations": ["source:weekly-sync.txt:chunk:0"],
            "chunks": [],
        }

    monkeypatch.setattr(graph_module, "answer_from_memory", fake_answer_from_memory)

    graph = build_graph()
    result = graph.invoke(
        {
            "question": "What did we decide?",
            "workspace_id": "workspace_123",
            "top_k": 3,
        }
    )

    assert result["answer"] == "Answered for workspace_123 with k=3"
    assert result["citations"] == ["source:weekly-sync.txt:chunk:0"]
    assert result["chunks"] == []
    assert result["selected_tool"] == "answer_from_memory"
    assert result["tool_call_count"] == 1


def test_list_tools_returns_phase3_tools() -> None:
    assert list_tools() == [
        "search_transcripts",
        "summarize_meeting",
        "extract_decisions",
        "find_action_items",
        "list_meetings",
        "answer_from_memory",
    ]


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


def test_graph_routes_action_item_questions_to_action_tool(monkeypatch: Any) -> None:
    def fake_find_action_items(
        *,
        query: str,
        workspace_id: str,
        top_k: int,
        session: AgentSession,
    ) -> dict[str, Any]:
        return {
            "action_items": [f"{workspace_id}: Dana will send the launch checklist"],
            "sources": ["source:weekly-sync.txt:chunk:2"],
        }

    monkeypatch.setattr(graph_module, "find_action_items", fake_find_action_items)

    graph = build_graph()
    result = graph.invoke(
        {
            "question": "What action items came from the launch meeting?",
            "workspace_id": "workspace_123",
        }
    )

    assert result["selected_tool"] == "find_action_items"
    assert result["answer"] == "workspace_123: Dana will send the launch checklist"
    assert result["citations"] == ["source:weekly-sync.txt:chunk:2"]


def test_tool_session_limit_blocks_excess_calls(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        tools_module,
        "search_memories",
        lambda query, workspace_id, top_k: [],
    )
    session = AgentSession(
        session_id="session_123",
        workspace_id="workspace_123",
        tool_call_count=20,
    )

    try:
        find_action_items(
            query="launch",
            workspace_id="workspace_123",
            session=session,
        )
    except RuntimeError as exc:
        assert str(exc) == "Tool call limit reached for this session"
    else:
        raise AssertionError("Expected tool limit error")
