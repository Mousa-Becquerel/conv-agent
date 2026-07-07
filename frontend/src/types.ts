// Shapes the API returns + UI-local message types.
//
// `User`, `ConversationSummary`, `ConversationDetail` mirror the FastAPI
// response models for /auth/me and /conversations exactly.
// `Message`, `AssistantMessage`, `UserMessage` are the client-side rendering
// shape — they wrap the server's MessageOut with streaming state.

export type Role = "user" | "assistant";

// ---------- Auth ----------
export interface User {
  id: string;
  email: string;
  display_name?: string | null;
  is_admin: boolean;
  created_at: string;
  last_login_at?: string | null;
}

// ---------- Conversation (server shapes) ----------
export interface ConversationSummary {
  id: string;
  title: string;
  doc_filter: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageOut {
  id: string;
  role: Role;
  content: string;
  payload?: AssistantPayload | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageOut[];
}

// ---------- Assistant payload (server-stored + streaming-incremental) ----------
export interface Source {
  doc_id: string;
  doc_title: string;
  section_kind: string;
  section_number: string;
  section_title: string;
  section_path: string;
  page_start: number;
  page_end: number;
  snippet: string;
  score?: number | null;
}

export interface SegmentWithCitations {
  text: string;
  citations: number[]; // 1-indexed into sources
}

export interface AssistantPayload {
  segments: SegmentWithCitations[];
  sources: Source[];
  related_articles: Source[];
  rewritten_query?: string | null;
  toolCall?: {
    query: string;
    doc_id: string | null;
    status: "running" | "complete";
    n_sources?: number;
    n_articles?: number;
  };
}

// ---------- Client-side message wrappers (with streaming flags) ----------
export interface UserMessage {
  id: string;
  role: "user";
  content: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  payload: AssistantPayload;
  streaming: boolean;
  error?: string;
}

export type Message = UserMessage | AssistantMessage;

// ---------- Backend doc_id values + label helpers ----------
export const DOC_IDS = {
  SOGL: "celex_32017r1485_it_txt",
  TIAD: "727-22tiad",
  SDM: "59",
} as const;

export type DocId = (typeof DOC_IDS)[keyof typeof DOC_IDS];
