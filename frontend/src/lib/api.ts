import type { SegmentWithCitations, Source } from "@/types";
import { authedFetch, getAccessToken, refreshAccess } from "./auth";
import { API_BASE } from "./config";

// API_BASE resolves to `/api` at the domain root or `/<prefix>/api` under a
// path-prefix deploy (via Vite's BASE_URL). Dev: Vite proxy in vite.config.ts
// forwards to http://localhost:8002. Prod: nginx inside the frontend
// container proxies to http://api:8000.

// ---------- Chat request/response shapes ----------
export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
  doc_id?: string | null;
  top_k_chunks?: number;
  top_n_articles?: number;
}

// ---------- Health ----------
export interface HealthResponse {
  status: string;
  qdrant_connected: boolean;
  collection_exists: boolean;
  points_count?: number | null;
}

export async function getHealth(): Promise<HealthResponse> {
  const r = await fetch(`${API_BASE}/health`);
  if (!r.ok) throw new Error(`health HTTP ${r.status}`);
  return (await r.json()) as HealthResponse;
}

// ---------- Streaming /chat/stream ----------
// Server SSE events (from api/app.py):
//   meta             — { mode: "pending", conversation_id }
//   tool_call_start  — { query, doc_id }
//   tool_call_end    — { n_sources, n_articles }
//   segment          — { index, text, citations[] }
//   done             — { sources, related_articles, query, conversation_id }
//   error            — { detail }
export interface StreamCallbacks {
  onMeta?: (meta: { mode: string; conversation_id: string }) => void;
  onToolCallStart?: (p: { query: string; doc_id: string | null }) => void;
  onToolCallEnd?: (p: { n_sources: number; n_articles: number }) => void;
  onSegment?: (seg: SegmentWithCitations & { index: number }) => void;
  onDone?: (final: {
    sources: Source[];
    related_articles: Source[];
    query: string;
    conversation_id: string;
  }) => void;
  onError?: (detail: string) => void;
}

/**
 * Open an SSE stream against /chat/stream with the access token attached.
 * On the initial 401 we refresh once and retry; further 401s mean the
 * session is dead and we surface that via onError (App.tsx routes to login).
 */
export async function streamChat(
  req: ChatRequest,
  cbs: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const access = getAccessToken();
  if (!access) {
    window.dispatchEvent(new CustomEvent("conv-agent:auth-expired"));
    cbs.onError?.("session expired");
    return;
  }

  const openStream = async (token: string): Promise<Response> =>
    fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(req),
      signal,
    });

  let resp = await openStream(access);

  if (resp.status === 401) {
    const fresh = await refreshAccess();
    if (!fresh) {
      window.dispatchEvent(new CustomEvent("conv-agent:auth-expired"));
      cbs.onError?.("session expired");
      return;
    }
    resp = await openStream(fresh);
  }

  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => `HTTP ${resp.status}`);
    cbs.onError?.(detail || `HTTP ${resp.status}`);
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // SSE parser — same as before.
  const handleEvent = (raw: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of raw.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const sep = line.indexOf(":");
      if (sep === -1) continue;
      const field = line.slice(0, sep);
      const value = line.slice(sep + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }
    if (!dataLines.length) return;
    let payload: unknown;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    switch (event) {
      case "meta":
        cbs.onMeta?.(payload as { mode: string; conversation_id: string });
        break;
      case "tool_call_start":
        cbs.onToolCallStart?.(payload as { query: string; doc_id: string | null });
        break;
      case "tool_call_end":
        cbs.onToolCallEnd?.(payload as { n_sources: number; n_articles: number });
        break;
      case "segment":
        cbs.onSegment?.(payload as SegmentWithCitations & { index: number });
        break;
      case "done":
        cbs.onDone?.(
          payload as {
            sources: Source[];
            related_articles: Source[];
            query: string;
            conversation_id: string;
          },
        );
        break;
      case "error":
        cbs.onError?.((payload as { detail: string }).detail || "stream error");
        break;
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      handleEvent(raw);
      boundary = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) handleEvent(buffer);
}

// ---------- Non-streaming fallback (kept for debugging) ----------
export interface ChatResponse {
  conversation_id: string;
  segments: SegmentWithCitations[];
  sources: Source[];
  related_articles: Source[];
  query: string;
  rewritten_query?: string | null;
}

export async function chat(req: ChatRequest): Promise<ChatResponse> {
  const r = await authedFetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`chat HTTP ${r.status}`);
  return (await r.json()) as ChatResponse;
}
