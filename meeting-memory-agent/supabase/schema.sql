-- Phase 1 Supabase setup for transcript chunk storage.
-- Run this in the Supabase SQL editor before calling the embedding pipeline.

-- WHAT THIS DOES: Enables pgvector so Postgres can store and compare embedding vectors.
-- WHY THIS MATTERS: The retrieval phase depends on cosine similarity search over this column.
create extension if not exists vector;

-- WHAT THIS DOES: Stores each sanitized transcript chunk with its embedding and source metadata.
-- WHY THIS MATTERS: The app searches this table to recover relevant meeting context later.
create table if not exists public.transcript_chunks (
    id uuid primary key default gen_random_uuid(),
    workspace_id text not null,
    filename text not null,
    filename_hash text not null,
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (length(content) > 0),
    embedding vector(768) not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (workspace_id, filename_hash, chunk_index)
);

-- WHAT THIS DOES: Speeds up duplicate checks during ingestion.
-- WHY THIS MATTERS: The embedder checks workspace_id + filename_hash before spending API calls.
create index if not exists transcript_chunks_dedup_idx
on public.transcript_chunks (workspace_id, filename_hash);

-- WHAT THIS DOES: Adds an approximate nearest-neighbor index for vector search.
-- WHY THIS MATTERS: Phase 2 retrieval should be fast once many chunks exist.
create index if not exists transcript_chunks_embedding_idx
on public.transcript_chunks
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

-- WHAT THIS DOES: Finds the transcript chunks closest to a query embedding for one workspace.
-- WHY THIS MATTERS: Phase 2 retrieval needs fast, tenant-scoped semantic search with similarity scores.
create or replace function public.match_transcript_chunks(
    query_embedding vector(768),
    match_workspace_id text,
    match_count integer default 5,
    match_threshold double precision default 0
)
returns table (
    id uuid,
    workspace_id text,
    filename text,
    chunk_index integer,
    content text,
    metadata jsonb,
    similarity double precision
)
language sql
stable
as $$
    select
        transcript_chunks.id,
        transcript_chunks.workspace_id,
        transcript_chunks.filename,
        transcript_chunks.chunk_index,
        transcript_chunks.content,
        transcript_chunks.metadata,
        1 - (transcript_chunks.embedding <=> query_embedding) as similarity
    from public.transcript_chunks
    where transcript_chunks.workspace_id = match_workspace_id
      and 1 - (transcript_chunks.embedding <=> query_embedding) >= match_threshold
    order by transcript_chunks.embedding <=> query_embedding
    limit match_count;
$$;

-- WHAT THIS DOES: Enables Row Level Security on meeting memory rows.
-- WHY THIS MATTERS: Multi-tenant data must not be readable across workspaces.
alter table public.transcript_chunks enable row level security;

-- Phase 1 note:
-- No public anon policies are added here. With RLS enabled, direct anon-client reads/writes are blocked.
-- Use server-side code with a tightly protected Supabase service-role key for ingestion, or add workspace
-- membership policies once auth/workspaces exist in Phase 4.
