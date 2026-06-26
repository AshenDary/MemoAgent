"""Tools exposed to the meeting memory agent."""

from __future__ import annotations

from typing import Any

from retrieval.retriever import answer_question, search_memories


# WHAT THIS DOES: Lists the currently available meeting-memory tools.
# WHY THIS MATTERS: Phase 3 can use this registry when LangGraph starts routing between tools.
def list_tools() -> list[str]:
    """Return available tool names."""
    return ["search_transcripts", "answer_from_memory"]


# WHAT THIS DOES: Runs semantic transcript search for a workspace.
# WHY THIS MATTERS: Agent tools should keep tenant boundaries explicit every time they touch stored memory.
def search_transcripts(
    *,
    query: str,
    workspace_id: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Search transcript chunks by semantic similarity."""
    return search_memories(query=query, workspace_id=workspace_id, top_k=top_k)


# WHAT THIS DOES: Retrieves relevant chunks and asks the RAG chain for a cited answer.
# WHY THIS MATTERS: This is the tool future agent-routing logic can call for normal user questions.
def answer_from_memory(
    *,
    question: str,
    workspace_id: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """Answer a question using the Phase 2 RAG core."""
    result = answer_question(question=question, workspace_id=workspace_id, top_k=top_k)
    if hasattr(result, "model_dump"):
        return result.model_dump()

    return result.dict()
