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

-- WHAT THIS DOES: Resolves the workspace scope from the authenticated Supabase JWT.
-- WHY THIS MATTERS: Row-level policies need a stable way to compare the current workspace to the row.
create or replace function public.current_workspace_id()
returns text
language sql
stable
as $$
    select coalesce(auth.jwt() ->> 'workspace_id', '');
$$;

-- WHAT THIS DOES: Limits transcript reads and writes to the caller's workspace.
-- WHY THIS MATTERS: One workspace must never read another workspace's transcript rows.
create policy transcript_chunks_select_own_workspace
on public.transcript_chunks
for select
using (workspace_id = public.current_workspace_id());

create policy transcript_chunks_insert_own_workspace
on public.transcript_chunks
for insert
with check (workspace_id = public.current_workspace_id());

-- WHAT THIS DOES: Stores per-session agent state without keeping it only in process memory.
-- WHY THIS MATTERS: Phase 4 needs durable session memory so tool-call history survives restarts.
create table if not exists public.agent_sessions (
    id uuid primary key default gen_random_uuid(),
    workspace_id text not null,
    session_id text not null,
    tool_call_count integer not null default 0 check (tool_call_count >= 0),
    conversation_history jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (workspace_id, session_id)
);

create index if not exists agent_sessions_workspace_idx
on public.agent_sessions (workspace_id);

alter table public.agent_sessions enable row level security;

-- WHAT THIS DOES: Keeps one workspace from reading or mutating another workspace's agent state.
-- WHY THIS MATTERS: Session memory is workspace-scoped and must not leak across tenants.
create policy agent_sessions_select_own_workspace
on public.agent_sessions
for select
using (workspace_id = public.current_workspace_id());

create policy agent_sessions_insert_own_workspace
on public.agent_sessions
for insert
with check (workspace_id = public.current_workspace_id());

create policy agent_sessions_update_own_workspace
on public.agent_sessions
for update
using (workspace_id = public.current_workspace_id())
with check (workspace_id = public.current_workspace_id());

-- WHAT THIS DOES: Stores hashed API keys for workspace-scoped backend authentication.
-- WHY THIS MATTERS: Phase 4 auth must never persist plaintext API keys.
create table if not exists public.api_keys (
    id uuid primary key default gen_random_uuid(),
    workspace_id text not null,
    key_id text not null unique,
    key_hash text not null check (length(key_hash) > 0),
    created_at timestamptz not null default now(),
    revoked_at timestamptz
);

create index if not exists api_keys_workspace_idx
on public.api_keys (workspace_id);

alter table public.api_keys enable row level security;

-- No client-side policy is defined for api_keys. The backend stores and checks hashes server-side,
-- and the service-role key bypasses RLS for these writes and lookups.

-- WHAT THIS DOES: Stores a safe audit trail for user queries and agent tool calls.
-- WHY THIS MATTERS: Teams need traceability without logging full private transcript content.
create table if not exists public.audit_logs (
    id uuid primary key default gen_random_uuid(),
    workspace_id text not null,
    session_id text,
    event_type text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists audit_logs_workspace_created_idx
on public.audit_logs (workspace_id, created_at desc);

alter table public.audit_logs enable row level security;

-- WHAT THIS DOES: Limits audit-log visibility to the owning workspace.
-- WHY THIS MATTERS: Audit trails should stay private even if a client key is reused incorrectly.
create policy audit_logs_select_own_workspace
on public.audit_logs
for select
using (workspace_id = public.current_workspace_id());

create policy audit_logs_insert_own_workspace
on public.audit_logs
for insert
with check (workspace_id = public.current_workspace_id());

-- Phase 1 note:
-- No public anon policies are added here. With RLS enabled, direct anon-client reads/writes are blocked.
-- Use server-side code with a tightly protected Supabase service-role key for ingestion, or add workspace
-- membership policies once auth/workspaces exist in Phase 4.
