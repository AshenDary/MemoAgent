# MemoAgent Frontend

This directory contains the Phase 5 Next.js client for MemoAgent.

## What it does

- Provides a chat-like interface for asking workspace-scoped questions
- Supports transcript uploads into the FastAPI backend
- Shows a compact answer stream with citation-oriented styling
- Reads the backend URL from `NEXT_PUBLIC_API_BASE_URL`

## Local setup

1. Install dependencies:

```bash
cd frontend
npm install
```

2. Copy the environment example and set the API base URL:

```bash
cp .env.example .env.local
```

3. Run the app:

```bash
npm run dev
```

## Notes

- The UI expects the FastAPI backend to be running separately.
- API requests use `X-API-Key` and the workspace ID supplied in the form.
- This scaffold is intentionally lightweight so it can be extended into the full Phase 5 product UI.
