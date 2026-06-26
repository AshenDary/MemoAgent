"""Tests for the Supabase schema and schema application helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.apply_supabase_schema import apply_schema


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "supabase" / "schema.sql"


def test_schema_defines_transcript_chunks_table() -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    assert "create table if not exists public.transcript_chunks" in schema_sql
    assert "embedding vector(768) not null" in schema_sql
    assert "create or replace function public.match_transcript_chunks" in schema_sql
    assert "alter table public.transcript_chunks enable row level security" in schema_sql


def test_apply_schema_executes_sql_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def execute(self, sql: str) -> None:
            calls.append(sql)

    class FakeConnection:
        def __init__(self) -> None:
            self.committed = False

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def commit(self) -> None:
            self.committed = True

    fake_connection = FakeConnection()
    monkeypatch.setattr("scripts.apply_supabase_schema.psycopg.connect", lambda db_url: fake_connection)

    apply_schema(db_url="postgresql://example", schema_sql="create table test(id int);")

    assert calls == ["create table test(id int);"]
    assert fake_connection.committed is True