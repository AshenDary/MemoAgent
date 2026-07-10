# MemoAgent Frontend

This is the Next.js interface for MemoAgent. It lets a user create or paste a
workspace access key, upload a transcript, ask meeting-memory questions, and
review the cited source snippets behind each answer.

## What Users See

- Workspace setup panel
- Transcript upload area for `.txt`, `.vtt`, and `.srt`
- Meeting ledger showing uploaded files
- Chat composer that unlocks only after a transcript is available
- Citation tabs that open the source drawer
- Backend status messages for upload, query, and key creation

## Local Setup

Install dependencies:

```bash
npm install
```

Run the frontend:

```bash
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

If `3000` is busy:

```bash
npm run dev -- -H 127.0.0.1 -p 3001
```

## Backend Connection

The frontend proxies browser requests through:

```text
/api/backend
```

By default, that proxy forwards to:

```text
http://127.0.0.1:8000
```

If your backend is somewhere else, create `.env.local`:

```env
API_BASE_URL=http://127.0.0.1:8000
```

For Vercel, set `API_BASE_URL` to the deployed Railway backend URL.

## Demo Flow

1. Start the backend.
2. Start the frontend.
3. Create an access key for a demo workspace.
4. Upload one of the fictional sample transcripts:
   - `../meeting-memory-agent/data/transcripts/demo/product-roadmap-review.vtt`
   - `../meeting-memory-agent/data/transcripts/demo/customer-onboarding-retrospective.srt`
5. Ask a question such as:
   - `What decisions were made?`
   - `What action items were assigned?`
   - `What did the team say about access keys?`

The chat composer is intentionally disabled until a transcript is uploaded or
loaded from the meeting ledger.

## Build Check

```bash
npm run build
```

## Deployment

Deploy this folder as the Vercel project root:

```text
frontend/
```

Required Vercel environment variable:

```env
API_BASE_URL=https://your-railway-backend.example.com
```

Do not add backend secrets such as `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`,
or `GEMINI_API_KEY` to public client-side variables.

## Notes For Portfolio Use

This UI is suitable for a portfolio demo with fictional transcripts. If you make
the URL public, consider disabling open key creation or limiting the demo
workspace so visitors cannot create unlimited API usage.
