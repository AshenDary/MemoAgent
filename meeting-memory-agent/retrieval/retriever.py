"""Semantic retrieval from pgvector."""


def search_memories(query: str, top_k: int = 5) -> list[dict]:
    """Placeholder retrieval function."""
    return [{"query": query, "rank": i + 1} for i in range(top_k)]
