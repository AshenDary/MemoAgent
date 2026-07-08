"use client";

import {
  ChangeEvent,
  DragEvent,
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState
} from "react";

type Role = "assistant" | "user";
type StatusTone = "idle" | "active" | "grounded" | "error";

type RetrievedChunk = {
  id?: string | null;
  workspace_id?: string;
  filename: string;
  chunk_index: number;
  content: string;
  metadata?: Record<string, unknown>;
  similarity?: number;
};

type Meeting = {
  workspace_id: string;
  filename: string;
  filename_hash: string;
  meeting_date?: string | null;
  chunk_count: number;
  latest_created_at?: string | null;
};

type Citation = {
  id: string;
  label: string;
  source: string;
  time: string;
  filename: string;
  chunkIndex: number;
  meetingDate?: string;
  excerpt?: string;
  similarity?: number;
};

type Message = {
  id: string;
  role: Role;
  content: string;
  citations?: Citation[];
  selectedTool?: string;
};

type Notice = {
  tone: StatusTone;
  text: string;
};

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_EXTENSIONS = [".txt", ".vtt", ".srt"];
const DEFAULT_TOP_K = 5;
const API_PROXY_BASE = "/api/backend";

const initialMessages: Message[] = [
  {
    id: "initial",
    role: "assistant",
    content:
      "Ask from the archive. Answers will stay tied to retrieved transcript evidence, and every source will appear as a ledger tab."
  }
];

export default function HomePage() {
  const [workspaceId, setWorkspaceId] = useState("workspace_123");
  const [apiKey, setApiKey] = useState("");
  const [sessionId] = useState(() => `session_${randomId()}`);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [citedMeetingIds, setCitedMeetingIds] = useState<Set<string>>(new Set());
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [notice, setNotice] = useState<Notice>({
    tone: "idle",
    text: "Backend idle"
  });
  const [isAsking, setIsAsking] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoadingMeetings, setIsLoadingMeetings] = useState(false);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadName, setUploadName] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

  const lastCitations = messages.flatMap((message) => message.citations ?? []).slice(-6);

  useEffect(() => {
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, [messages, isAsking]);

  async function handleCreateKey() {
    if (!workspaceId.trim()) {
      setNotice({ tone: "error", text: "Workspace ID is required before creating a key." });
      return;
    }

    setIsCreatingKey(true);
    setNotice({ tone: "active", text: "Creating workspace key" });

    try {
      const response = await fetch(`${API_PROXY_BASE}/auth/create-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId.trim() })
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new Error(errorDetail(payload, "Key creation failed."));
      }

      setApiKey(String(payload.api_key ?? ""));
      setNotice({ tone: "grounded", text: "Key created. Store it now; the API only returns it once." });
    } catch (error) {
      setNotice({
        tone: "error",
        text: errorMessage(error, "Key creation failed. Confirm the backend is running on port 8000.")
      });
    } finally {
      setIsCreatingKey(false);
    }
  }

  async function handleRefreshMeetings() {
    if (!apiKey.trim()) {
      setNotice({ tone: "error", text: "Add an API key to list workspace meetings." });
      return;
    }

    setIsLoadingMeetings(true);
    setNotice({ tone: "active", text: "Reading meeting ledger" });

    try {
      const params = new URLSearchParams({ workspace_id: workspaceId.trim() });
      const response = await fetch(`${API_PROXY_BASE}/meetings?${params.toString()}`, {
        headers: { "X-API-Key": apiKey.trim() }
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new Error(errorDetail(payload, "Meeting list failed."));
      }

      const rows = Array.isArray(payload.meetings) ? (payload.meetings as Meeting[]) : [];
      setMeetings(rows.length > 0 ? rows : []);
      setNotice({
        tone: "grounded",
        text: rows.length > 0 ? `${rows.length} meetings loaded` : "No meetings stored yet"
      });
    } catch (error) {
      setNotice({ tone: "error", text: errorMessage(error, "Meeting list failed.") });
    } finally {
      setIsLoadingMeetings(false);
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setNotice({ tone: "error", text: "Enter a question before querying memory." });
      return;
    }
    if (!apiKey.trim()) {
      setNotice({ tone: "error", text: "Add an API key to query this workspace." });
      return;
    }

    setIsAsking(true);
    setNotice({ tone: "active", text: "Searching meeting memory" });
    setQuestion("");
    setMessages((current) => [
      ...current,
      { id: randomId(), role: "user", content: trimmedQuestion }
    ]);

    try {
      const response = await fetch(`${API_PROXY_BASE}/agent/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey.trim()
        },
        body: JSON.stringify({
          workspace_id: workspaceId.trim(),
          session_id: sessionId,
          message: trimmedQuestion,
          top_k: DEFAULT_TOP_K
        })
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new Error(errorDetail(payload, "Query failed."));
      }

      const chunks = Array.isArray(payload.chunks) ? (payload.chunks as RetrievedChunk[]) : [];
      const rawCitations = Array.isArray(payload.citations) ? payload.citations.map(String) : [];
      const citations = buildCitations(rawCitations, chunks);
      setCitedMeetingIds((current) => addCitedMeetings(current, chunks));
      setMessages((current) => [
        ...current,
        {
          id: randomId(),
          role: "assistant",
          content: String(payload.answer ?? "No answer returned."),
          citations,
          selectedTool: humanToolName(payload.selected_tool)
        }
      ]);
      setNotice({
        tone: citations.length > 0 ? "grounded" : "idle",
        text: citations.length > 0 ? `${citations.length} citations grounded` : "Answer returned without citations"
      });
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: randomId(),
          role: "assistant",
          content: errorMessage(error, "Query failed.")
        }
      ]);
      setNotice({ tone: "error", text: errorMessage(error, "Query failed.") });
    } finally {
      setIsAsking(false);
    }
  }

  async function handleUploadFile(file: File) {
    if (!apiKey.trim()) {
      setNotice({ tone: "error", text: "Add an API key before uploading a transcript." });
      return;
    }

    const validationError = validateTranscript(file);
    if (validationError) {
      setNotice({ tone: "error", text: validationError });
      return;
    }

    setIsUploading(true);
    setUploadName(file.name);
    setUploadProgress(18);
    setNotice({ tone: "active", text: "Uploading transcript" });

    try {
      const formData = new FormData();
      formData.append("workspace_id", workspaceId.trim());
      formData.append("file", file);

      const response = await fetch(`${API_PROXY_BASE}/upload`, {
        method: "POST",
        headers: { "X-API-Key": apiKey.trim() },
        body: formData
      });
      setUploadProgress(82);
      const payload = await readJson(response);
      if (!response.ok) {
        throw new Error(errorDetail(payload, "Upload failed."));
      }

      setUploadProgress(100);
      setNotice({
        tone: "grounded",
        text: `${payload.filename ?? file.name} is now searchable`
      });
      await handleRefreshMeetings();
    } catch (error) {
      setNotice({ tone: "error", text: errorMessage(error, "Upload failed.") });
    } finally {
      window.setTimeout(() => {
        setIsUploading(false);
        setUploadProgress(0);
      }, 350);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      void handleUploadFile(file);
    }
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) {
      void handleUploadFile(file);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <main className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "is-open" : ""}`} aria-label="Workspace">
        <div className="sidebar-header">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Meeting Memory</h1>
          </div>
          <button className="icon-button mobile-only" type="button" onClick={() => setSidebarOpen(false)}>
            Close
          </button>
        </div>

        <section className="control-group" aria-label="Workspace credentials">
          <label>
            <span>Workspace code</span>
            <input value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} />
          </label>
          <label>
            <span>Access key</span>
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="mma_..."
              type="password"
            />
          </label>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={handleCreateKey} disabled={isCreatingKey}>
              {isCreatingKey ? "Creating" : "Create key"}
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={handleRefreshMeetings}
              disabled={isLoadingMeetings}
            >
              {isLoadingMeetings ? "Reading" : "Refresh"}
            </button>
          </div>
        </section>

        <section className="control-group" aria-label="Upload transcript">
          <div className="section-heading">
            <h2>Upload</h2>
            <span className="mono-note">10MB max</span>
          </div>
          <label
            className={`upload-zone ${isDragging ? "is-dragging" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.vtt,.srt,text/plain,text/vtt"
              onChange={handleFileChange}
            />
            <span>Upload transcript</span>
            <small>{isUploading ? "Uploading" : uploadName || ".txt, .vtt, .srt"}</small>
            <i style={{ width: `${uploadProgress}%` }} />
          </label>
        </section>

        <section className="meeting-ledger" aria-label="Meetings">
          <div className="section-heading">
            <h2>Meetings</h2>
            <span className="mono-note">{meetings.length}</span>
          </div>
          {meetings.length === 0 ? (
            <div className="empty-block">
              <h3>Nothing recorded yet.</h3>
              <button className="secondary-button" type="button" onClick={() => fileInputRef.current?.click()}>
                Upload transcript
              </button>
            </div>
          ) : (
            <ol>
              {meetings.map((meeting) => (
                <li key={meeting.filename_hash}>
                  <button type="button" className="meeting-row" onClick={() => setSidebarOpen(false)}>
                    <span className="meeting-date">{formatDate(meeting.meeting_date ?? meeting.latest_created_at)}</span>
                    <strong>{meeting.filename}</strong>
                    <span className="meeting-meta">Searchable transcript</span>
                    {citedMeetingIds.has(meeting.filename_hash) || citedMeetingIds.has(meeting.filename) ? (
                      <span className="verified-dot" aria-label="Cited" />
                    ) : null}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>
      </aside>

      <section className="chat-pane" aria-label="Conversation">
        <header className="topbar">
          <button className="secondary-button mobile-only" type="button" onClick={() => setSidebarOpen(true)}>
            Workspace
          </button>
          <div>
            <span className={`status-pill ${notice.tone}`}>{notice.text}</span>
            <p>Meeting answers are grounded in uploaded transcripts.</p>
          </div>
        </header>

        <div className="thread" ref={threadRef}>
          {messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <div className="message-label">
                <span>{message.role === "assistant" ? "MEMOAGENT" : "YOU"}</span>
                {message.selectedTool ? <em>{message.selectedTool}</em> : null}
              </div>
              <p>{message.content}</p>
              {message.citations && message.citations.length > 0 ? (
                <div className="citation-line" aria-label="Citations">
                  {message.citations.map((citation) => (
                    <button
                      key={citation.id}
                      className="citation-stamp"
                      type="button"
                      onClick={() => setSelectedCitation(citation)}
                    >
                      {citation.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
          {isAsking ? (
            <article className="message assistant">
              <div className="message-label">
                <span>MEMOAGENT</span>
                <em>searching</em>
              </div>
              <div className="answer-skeleton" aria-label="Answer loading" />
            </article>
          ) : null}
        </div>

        <form className="composer" onSubmit={handleAsk}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Ask what the team decided, assigned, or deferred..."
            rows={1}
          />
          <button className="primary-button" type="submit" disabled={isAsking}>
            {isAsking ? "Querying" : "Ask memory"}
          </button>
        </form>
      </section>

      <aside className={`source-drawer ${selectedCitation ? "is-open" : ""}`} aria-label="Source drawer">
        <div className="drawer-header">
          <div>
            <p className="eyebrow">Source</p>
            <h2>{selectedCitation?.label ?? "No citation selected"}</h2>
          </div>
          <button className="icon-button" type="button" onClick={() => setSelectedCitation(null)}>
            Close
          </button>
        </div>

        {selectedCitation ? (
          <div className="source-body">
            <dl>
              <div>
                <dt>File</dt>
                <dd>{selectedCitation.filename}</dd>
              </div>
              <div>
                <dt>Meeting date</dt>
                <dd>{selectedCitation.meetingDate ?? "Unknown"}</dd>
              </div>
              <div>
                <dt>Source tab</dt>
                <dd>{selectedCitation.label}</dd>
              </div>
            </dl>
            <blockquote>{selectedCitation.excerpt ?? "No transcript excerpt returned for this citation."}</blockquote>
          </div>
        ) : (
          <div className="source-body empty-block">
            <h3>Select a ledger tab.</h3>
            <p>Retrieved excerpts and source metadata will appear here.</p>
          </div>
        )}

        {lastCitations.length > 0 ? (
          <div className="recent-citations">
            <h3>Recent citations</h3>
            {lastCitations.map((citation) => (
              <button key={citation.id} type="button" onClick={() => setSelectedCitation(citation)}>
                {citation.label}
              </button>
            ))}
          </div>
        ) : null}
      </aside>
    </main>
  );
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    return (await response.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function errorDetail(payload: Record<string, unknown>, fallback: string): string {
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => JSON.stringify(item)).join(" ");
  }
  return fallback;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function validateTranscript(file: File): string | null {
  const lowerName = file.name.toLowerCase();
  const hasAllowedExtension = ALLOWED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
  if (!hasAllowedExtension) {
    return "Unsupported transcript format. Upload .txt, .vtt, or .srt.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "File exceeds 10MB. Split the transcript or trim before uploading.";
  }
  if (file.size === 0) {
    return "Transcript file is empty. Upload a file with meeting text.";
  }
  return null;
}

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function buildCitations(labels: string[], chunks: RetrievedChunk[]): Citation[] {
  const citationLabels = labels.length > 0 ? labels : chunks.map((chunk) => chunkLabel(chunk));
  return citationLabels.map((rawLabel, index) => {
    const chunk = chunks[index] ?? findChunkForLabel(rawLabel, chunks);
    const filename = chunk?.filename ?? parseSource(rawLabel) ?? "meeting";
    const chunkIndex = chunk?.chunk_index ?? parseChunkIndex(rawLabel) ?? index;
    const meetingDate = asString(chunk?.metadata?.meeting_date) ?? parseDate(rawLabel);

    return {
      id: `${rawLabel}-${index}`,
      label: ledgerLabel(filename, chunkIndex, meetingDate),
      source: rawLabel,
      time: chunkTime(chunkIndex),
      filename,
      chunkIndex,
      meetingDate,
      excerpt: chunk?.content,
      similarity: chunk?.similarity
    };
  });
}

function findChunkForLabel(label: string, chunks: RetrievedChunk[]): RetrievedChunk | undefined {
  const source = parseSource(label);
  const index = parseChunkIndex(label);
  return chunks.find((chunk) => {
    const sourceMatches = source ? chunk.filename === source : true;
    const indexMatches = typeof index === "number" ? chunk.chunk_index === index : true;
    return sourceMatches && indexMatches;
  });
}

function chunkLabel(chunk: RetrievedChunk): string {
  const date = asString(chunk.metadata?.meeting_date);
  return `source:${chunk.filename}:chunk:${chunk.chunk_index}${date ? `:date:${date}` : ""}`;
}

function parseSource(label: string): string | null {
  const match = label.match(/source:(.*?):chunk:/);
  return match?.[1] ?? null;
}

function parseChunkIndex(label: string): number | null {
  const match = label.match(/:chunk:(\d+)/);
  return match ? Number(match[1]) : null;
}

function parseDate(label: string): string | undefined {
  const match = label.match(/:date:([0-9-]+)/);
  return match?.[1];
}

function ledgerLabel(filename: string, chunkIndex: number, meetingDate?: string): string {
  const source = filename
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-z0-9]+/gi, "")
    .slice(0, 3)
    .toUpperCase()
    .padEnd(3, "X");
  const dateCode = meetingDate ? meetingDate.slice(5).replace("-", "") : String(chunkIndex).padStart(4, "0");
  return `[ ${source}·${dateCode}  ${chunkTime(chunkIndex)} ]`;
}

function chunkTime(chunkIndex: number): string {
  const minutes = Math.max(0, chunkIndex) * 2;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function addCitedMeetings(current: Set<string>, chunks: RetrievedChunk[]): Set<string> {
  const next = new Set(current);
  chunks.forEach((chunk) => {
    const filenameHash = asString(chunk.metadata?.filename_hash);
    if (filenameHash) {
      next.add(filenameHash);
    }
    if (chunk.filename) {
      next.add(chunk.filename);
    }
  });
  return next;
}

function humanToolName(value: unknown): string {
  const toolName = typeof value === "string" ? value : "answer_from_memory";
  const labels: Record<string, string> = {
    answer_from_memory: "answered from memory",
    search_transcripts: "searched transcripts",
    summarize_meeting: "summarized meeting",
    extract_decisions: "found decisions",
    find_action_items: "found action items",
    list_meetings: "listed meetings"
  };
  return labels[toolName] ?? "answered from memory";
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "undated";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    year: "numeric"
  }).format(date);
}
