// REST client for the server-side conversation store.
// Replaces the localStorage v2 conversation state from earlier phases.

import { authedFetch } from "./auth";
import type { ConversationDetail, ConversationSummary } from "@/types";
import { API_BASE } from "./config";

export async function listConversations(): Promise<ConversationSummary[]> {
  const r = await authedFetch(`${API_BASE}/conversations`);
  if (!r.ok) throw new Error(`list conversations HTTP ${r.status}`);
  return (await r.json()) as ConversationSummary[];
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const r = await authedFetch(`${API_BASE}/conversations/${id}`);
  if (!r.ok) throw new Error(`get conversation HTTP ${r.status}`);
  return (await r.json()) as ConversationDetail;
}

export async function patchConversation(
  id: string,
  patch: { title?: string; doc_filter?: string | null },
): Promise<ConversationSummary> {
  const body = {
    title: patch.title,
    // Server treats empty string as "clear filter"; null means leave alone.
    doc_filter:
      patch.doc_filter === null
        ? ""
        : patch.doc_filter === undefined
          ? undefined
          : patch.doc_filter,
  };
  const r = await authedFetch(`${API_BASE}/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`patch conversation HTTP ${r.status}`);
  return (await r.json()) as ConversationSummary;
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await authedFetch(`${API_BASE}/conversations/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`delete conversation HTTP ${r.status}`);
}
