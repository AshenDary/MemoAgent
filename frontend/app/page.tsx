"use client";

import { FormEvent, useMemo, useState } from 'react';

type Message = {
  role: 'assistant' | 'user';
  content: string;
};

const initialMessages: Message[] = [
  {
    role: 'assistant',
    content:
      'Drop in a transcript, ask a question, and I will answer with citations from the connected workspace.'
  }
];

const sampleCitations = [
  'Q4 planning review · 2026-07-01',
  'Customer escalation retro · 2026-06-28',
  'Sprint sync · 2026-06-24'
];

export default function HomePage() {
  const [workspaceId, setWorkspaceId] = useState('workspace_123');
  const [apiKey, setApiKey] = useState('');
  const [question, setQuestion] = useState('What did we decide about onboarding?');
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [uploadName, setUploadName] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const endpoint = useMemo(() => {
    return process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';
  }, []);

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!apiKey.trim()) {
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: 'Provide an API key to query the workspace.'
        }
      ]);
      return;
    }

    setIsBusy(true);
    setMessages((current) => [...current, { role: 'user', content: question }]);

    try {
      const response = await fetch(`${endpoint}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          question,
          top_k: 5
        })
      });
      const payload = await response.json();
      const answer = payload.answer ?? 'No answer returned.';
      setMessages((current) => [...current, { role: 'assistant', content: answer }]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: error instanceof Error ? error.message : 'Query request failed.'
        }
      ]);
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const file = formData.get('file');
    if (!(file instanceof File)) {
      return;
    }

    setUploadName(file.name);
    setIsBusy(true);

    try {
      const upload = new FormData();
      upload.append('workspace_id', workspaceId);
      upload.append('file', file);

      const response = await fetch(`${endpoint}/upload`, {
        method: 'POST',
        headers: {
          'X-API-Key': apiKey
        },
        body: upload
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }

      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: `Uploaded ${file.name} and queued it for ingestion.`
        }
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: error instanceof Error ? error.message : 'Upload request failed.'
        }
      ]);
    } finally {
      setIsBusy(false);
      form.reset();
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">MemoAgent Phase 5</p>
          <h1>Meeting memory with sharp answers and workspace isolation.</h1>
          <p className="lede">
            A focused client for querying transcripts, uploading new meetings, and reviewing
            grounded answers with citations.
          </p>
          <div className="stats">
            {sampleCitations.map((item) => (
              <span key={item} className="stat-pill">
                {item}
              </span>
            ))}
          </div>
        </div>
        <div className="hero-panel">
          <div className="panel-card">
            <span>API endpoint</span>
            <strong>{endpoint}</strong>
          </div>
          <div className="panel-card">
            <span>Workspace</span>
            <strong>{workspaceId}</strong>
          </div>
          <div className="panel-card">
            <span>Status</span>
            <strong>{isBusy ? 'Working' : 'Ready'}</strong>
          </div>
        </div>
      </section>

      <section className="workspace-grid">
        <form className="card input-card" onSubmit={handleAsk}>
          <div className="card-heading">
            <h2>Ask a question</h2>
            <p>Queries go to the FastAPI backend with the workspace-scoped API key.</p>
          </div>
          <label>
            Workspace ID
            <input value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} />
          </label>
          <label>
            API Key
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="mma_..."
            />
          </label>
          <label>
            Question
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={5} />
          </label>
          <button type="submit" disabled={isBusy}>
            {isBusy ? 'Working...' : 'Send query'}
          </button>
        </form>

        <form className="card upload-card" onSubmit={handleUpload}>
          <div className="card-heading">
            <h2>Upload transcript</h2>
            <p>Accepts raw transcript files and forwards them to the ingestion endpoint.</p>
          </div>
          <label>
            Transcript file
            <input type="file" name="file" accept=".txt,.vtt,.srt" />
          </label>
          <button type="submit" disabled={isBusy}>
            {isBusy ? 'Working...' : 'Upload file'}
          </button>
          {uploadName ? <p className="upload-note">Latest file: {uploadName}</p> : null}
        </form>
      </section>

      <section className="card transcript-card">
        <div className="card-heading">
          <h2>Conversation</h2>
          <p>Responses are designed to stay grounded in transcript evidence.</p>
        </div>
        <div className="message-list">
          {messages.map((message, index) => (
            <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
              <span>{message.role}</span>
              <p>{message.content}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
