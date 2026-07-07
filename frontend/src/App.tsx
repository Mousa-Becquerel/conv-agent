import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { AIDisclaimerFooter } from "@/components/ui/AIDisclaimerFooter";
import { AIDisclaimerModal } from "@/components/ui/AIDisclaimerModal";
import { ConversationView } from "@/components/ui/ConversationView";
import { Logo } from "@/components/ui/Logo";
import { LoginScreen } from "@/components/ui/LoginScreen";
import { PrivacyPage } from "@/components/ui/PrivacyPage";
import { Sidebar } from "@/components/ui/Sidebar";
import { VoiceDisclosureModal } from "@/components/ui/VoiceDisclosureModal";
import { WelcomeScreen } from "@/components/ui/WelcomeScreen";
import { streamChat } from "@/lib/api";
import { getMe, logout as authLogout } from "@/lib/auth";
import {
  deleteConversation as apiDeleteConversation,
  getConversation,
  listConversations,
} from "@/lib/conversations";
import { setSentryUser } from "@/lib/sentry";
import {
  loadDisclaimerAck,
  loadSidebarOpen,
  loadVoiceDisclosureAck,
  pruneLegacyStorage,
  saveDisclaimerAck,
  saveSidebarOpen,
  saveVoiceDisclosureAck,
} from "@/lib/storage";
import { newId } from "@/lib/utils";
import { DOC_IDS } from "@/types";
import type {
  AssistantMessage,
  ConversationSummary,
  Message,
  Source,
  User,
  UserMessage,
} from "@/types";

const DOC_FILTER_LABELS: Record<string, string> = {
  [DOC_IDS.SOGL]: "SOGL (UE 2017/1485)",
  [DOC_IDS.TIAD]: "TIAD — Autoconsumo",
  [DOC_IDS.SDM]: "Sistema di Misura",
};

type View = "chat" | "privacy";
type AuthStatus = "loading" | "anonymous" | "authed";

export function App() {
  // ---------- top-level UI state ----------
  const [authStatus, setAuthStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>("chat");
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => loadSidebarOpen());
  const [disclaimerOpen, setDisclaimerOpen] = useState<boolean>(false);
  // Voice-disclosure modal — shown the first time the user clicks the mic.
  // The resolver is stashed in a ref so the modal action handlers can
  // complete the in-flight promise returned by `handleVoiceBeforeFirstUse`.
  const [voiceModalOpen, setVoiceModalOpen] = useState<boolean>(false);
  const voiceModalResolverRef = useRef<((ok: boolean) => void) | null>(null);

  // ---------- conversations ----------
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeMessages, setActiveMessages] = useState<Message[]>([]);
  const [activeDocFilter, setActiveDocFilter] = useState<string | null>(null);
  const [activeLoading, setActiveLoading] = useState(false);
  const [pendingDocFilter, setPendingDocFilter] = useState<string | null>(null); // for new-conv welcome screen
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  // Set to true whenever we adopt an activeId from the streaming response
  // (a new conversation was just created server-side). The "load active
  // conversation" effect honors this flag and skips its fetch — otherwise
  // it overwrites the in-flight streaming state with a server view that
  // doesn't include the assistant message yet (race condition).
  const skipNextFetchRef = useRef(false);

  // ---------- boot: prune old state, check auth, listen for expiry ----------
  useEffect(() => {
    pruneLegacyStorage();
    (async () => {
      try {
        const me = await getMe();
        setUser(me);
        setSentryUser({ id: me.id, email: me.email });
        setAuthStatus("authed");
      } catch {
        setSentryUser(null);
        setAuthStatus("anonymous");
      }
    })();

    const onExpired = () => {
      setUser(null);
      setSentryUser(null);
      setAuthStatus("anonymous");
      setConversations([]);
      setActiveId(null);
      setActiveMessages([]);
    };
    window.addEventListener("conv-agent:auth-expired", onExpired);
    return () => window.removeEventListener("conv-agent:auth-expired", onExpired);
  }, []);

  // ---------- once authed, load conversations list + disclaimer state ----------
  useEffect(() => {
    if (authStatus !== "authed") return;
    setDisclaimerOpen(!loadDisclaimerAck());
    (async () => {
      try {
        const list = await listConversations();
        setConversations(list);
      } catch {
        setConversations([]);
      }
    })();
  }, [authStatus]);

  // ---------- persist sidebar collapsed state ----------
  useEffect(() => {
    saveSidebarOpen(sidebarOpen);
  }, [sidebarOpen]);

  // ---------- load active conversation's messages on selection ----------
  useEffect(() => {
    if (authStatus !== "authed" || !activeId) {
      setActiveMessages([]);
      setActiveDocFilter(null);
      return;
    }
    // We just adopted this activeId mid-stream — local state is the source
    // of truth. Skip the server fetch (it would race the persistence of
    // the assistant turn).
    if (skipNextFetchRef.current) {
      skipNextFetchRef.current = false;
      return;
    }
    setActiveLoading(true);
    let cancelled = false;
    (async () => {
      try {
        const detail = await getConversation(activeId);
        if (cancelled) return;
        const msgs: Message[] = detail.messages.map((m) =>
          m.role === "user"
            ? { id: m.id, role: "user", content: m.content }
            : {
                id: m.id,
                role: "assistant",
                streaming: false,
                payload: m.payload ?? {
                  segments: [],
                  sources: [],
                  related_articles: [],
                },
              },
        );
        setActiveMessages(msgs);
        setActiveDocFilter(detail.doc_filter ?? null);
      } catch {
        // Conversation might have been deleted in another tab. Reset to welcome.
        if (!cancelled) {
          setActiveId(null);
          setActiveMessages([]);
        }
      } finally {
        if (!cancelled) setActiveLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, authStatus]);

  // ---------- derived ----------
  const docFilterLabel = useMemo(() => {
    const docFilter = activeId ? activeDocFilter : pendingDocFilter;
    if (!docFilter) return "Tutti i documenti";
    return DOC_FILTER_LABELS[docFilter] ?? docFilter;
  }, [activeId, activeDocFilter, pendingDocFilter]);

  const sortedConversations = useMemo(
    () =>
      [...conversations].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      ),
    [conversations],
  );

  // ---------- handlers ----------
  const handleLoggedIn = useCallback((u: User) => {
    setUser(u);
    setSentryUser({ id: u.id, email: u.email });
    setAuthStatus("authed");
  }, []);

  const handleLogout = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    authLogout();
    setUser(null);
    setSentryUser(null);
    setConversations([]);
    setActiveId(null);
    setActiveMessages([]);
    setAuthStatus("anonymous");
    setView("chat");
  }, []);

  const handleNewConversation = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setActiveId(null);
    setActiveMessages([]);
    setPendingDocFilter(null);
    setView("chat");
  }, []);

  const handleSelectConversation = useCallback(
    (id: string) => {
      if (id === activeId) return;
      abortRef.current?.abort();
      abortRef.current = null;
      setIsStreaming(false);
      setActiveId(id);
      setView("chat");
    },
    [activeId],
  );

  const handleDeleteConversation = useCallback(
    async (id: string) => {
      try {
        await apiDeleteConversation(id);
      } catch {
        // Even if the API call fails (network) drop the local entry — they
        // can retry from the next reload.
      }
      setConversations((prev) => {
        const remaining = prev.filter((c) => c.id !== id);
        if (id === activeId) {
          const next = remaining[0];
          if (next) {
            setActiveId(next.id);
          } else {
            setActiveId(null);
            setActiveMessages([]);
          }
        }
        return remaining;
      });
    },
    [activeId],
  );

  const handleSetDocFilter = useCallback(
    (value: string | null) => {
      // Only used on the welcome screen for a brand-new conversation. Once a
      // conversation exists, doc_filter is persisted server-side via the chat
      // request and surfaced read-only here.
      setPendingDocFilter(value);
    },
    [],
  );

  // ---------- mutate the active conversation's last assistant message ----------
  const mutateLastAssistant = useCallback(
    (fn: (a: AssistantMessage) => AssistantMessage) => {
      setActiveMessages((prev) => {
        const last = prev[prev.length - 1];
        if (!last || last.role !== "assistant") return prev;
        return [...prev.slice(0, -1), fn(last)];
      });
    },
    [],
  );

  // ---------- send a message ----------
  const handleSend = useCallback(
    async (text: string) => {
      if (isStreaming) return;
      const trimmed = text.trim();
      if (!trimmed) return;

      const userMsg: UserMessage = { id: newId(), role: "user", content: trimmed };
      const placeholder: AssistantMessage = {
        id: newId(),
        role: "assistant",
        streaming: true,
        payload: { segments: [], sources: [], related_articles: [] },
      };

      // Optimistic append.
      setActiveMessages((prev) => [...prev, userMsg, placeholder]);
      setIsStreaming(true);

      const isNew = activeId === null;
      const docIdForThisTurn = isNew ? pendingDocFilter : activeDocFilter;

      const controller = new AbortController();
      abortRef.current = controller;

      let newConversationId: string | null = null;

      try {
        await streamChat(
          {
            message: trimmed,
            conversation_id: activeId ?? undefined,
            doc_id: docIdForThisTurn ?? undefined,
          },
          {
            onMeta: ({ conversation_id }) => {
              if (conversation_id && !activeId) {
                newConversationId = conversation_id;
                // Tell the "load on activeId change" effect to leave the
                // in-flight streaming state alone.
                skipNextFetchRef.current = true;
                setActiveId(conversation_id);
                if (isNew && pendingDocFilter !== null) {
                  setActiveDocFilter(pendingDocFilter);
                  setPendingDocFilter(null);
                }
              }
            },
            onToolCallStart: ({ query, doc_id }) => {
              mutateLastAssistant((a) => ({
                ...a,
                payload: {
                  ...a.payload,
                  toolCall: { query, doc_id, status: "running" },
                },
              }));
            },
            onToolCallEnd: ({ n_sources, n_articles }) => {
              mutateLastAssistant((a) => ({
                ...a,
                payload: {
                  ...a.payload,
                  toolCall: a.payload.toolCall
                    ? { ...a.payload.toolCall, status: "complete", n_sources, n_articles }
                    : undefined,
                },
              }));
            },
            onSegment: (seg) => {
              mutateLastAssistant((a) => {
                const segments = [...a.payload.segments];
                while (segments.length <= seg.index) {
                  segments.push({ text: "", citations: [] });
                }
                segments[seg.index] = { text: seg.text, citations: seg.citations };
                return { ...a, payload: { ...a.payload, segments } };
              });
            },
            onDone: (final: {
              sources: Source[];
              related_articles: Source[];
              query: string;
              conversation_id: string;
            }) => {
              if (final.conversation_id && !newConversationId && !activeId) {
                newConversationId = final.conversation_id;
                skipNextFetchRef.current = true;
                setActiveId(final.conversation_id);
              }
              mutateLastAssistant((a) => ({
                ...a,
                streaming: false,
                payload: {
                  ...a.payload,
                  sources: final.sources,
                  related_articles: final.related_articles,
                },
              }));
            },
            onError: (detail) => {
              mutateLastAssistant((a) => ({ ...a, streaming: false, error: detail }));
            },
          },
          controller.signal,
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        mutateLastAssistant((a) => ({ ...a, streaming: false, error: msg }));
      } finally {
        setIsStreaming(false);
        abortRef.current = null;

        // Refresh the sidebar list so the new conversation appears (or the
        // existing one bubbles to the top).
        try {
          const list = await listConversations();
          setConversations(list);
        } catch {
          // ignore — next page load will catch up
        }
        // Clear pendingDocFilter regardless — it only mattered for the new convo turn.
        if (isNew) setPendingDocFilter(null);
        void newConversationId; // mark intentionally captured
      }
    },
    [activeId, activeDocFilter, isStreaming, mutateLastAssistant, pendingDocFilter],
  );

  // ---------- disclaimer ----------
  const handleAcknowledgeDisclaimer = useCallback(() => {
    saveDisclaimerAck();
    setDisclaimerOpen(false);
  }, []);

  const openPrivacy = useCallback(() => setView("privacy"), []);
  const closePrivacy = useCallback(() => setView("chat"), []);

  // ---------- voice disclosure gate ----------
  // Returns true if the user has already acknowledged voice transcription,
  // or once they click "Continua" in the modal. False on "Annulla" or
  // closure. Async so VoiceInputButton can await it before requesting mic.
  const handleVoiceBeforeFirstUse = useCallback(async (): Promise<boolean> => {
    if (loadVoiceDisclosureAck()) return true;
    return new Promise<boolean>((resolve) => {
      voiceModalResolverRef.current = resolve;
      setVoiceModalOpen(true);
    });
  }, []);

  const handleVoiceAllow = useCallback(() => {
    saveVoiceDisclosureAck();
    voiceModalResolverRef.current?.(true);
    voiceModalResolverRef.current = null;
    setVoiceModalOpen(false);
  }, []);

  const handleVoiceCancel = useCallback(() => {
    voiceModalResolverRef.current?.(false);
    voiceModalResolverRef.current = null;
    setVoiceModalOpen(false);
  }, []);

  // ---------- render ----------
  if (authStatus === "loading") {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background gap-4">
        <Logo className="h-5 w-auto" />
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (authStatus === "anonymous") {
    if (view === "privacy") {
      return <PrivacyPage onBack={closePrivacy} />;
    }
    return <LoginScreen onLoggedIn={handleLoggedIn} onOpenPrivacy={openPrivacy} />;
  }

  if (view === "privacy") {
    return <PrivacyPage onBack={closePrivacy} />;
  }

  // Show the welcome screen ONLY when there's neither a conversation loaded
  // nor any optimistic messages queued locally. Using `||` here meant the
  // first send stayed stuck on the welcome screen until `onMeta` set
  // `activeId` — by that time segments were already arriving, so the user
  // saw no loading state and the reply landed all at once.
  const showWelcome = !activeId && activeMessages.length === 0;

  const mainView = activeLoading ? (
    <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
      <Loader2 className="w-4 h-4 animate-spin mr-2" />
      Caricamento conversazione…
    </div>
  ) : showWelcome ? (
    <WelcomeScreen
      onSend={handleSend}
      docFilter={pendingDocFilter}
      onDocFilterChange={handleSetDocFilter}
      onVoiceBeforeFirstUse={handleVoiceBeforeFirstUse}
    />
  ) : (
    <ConversationView
      messages={activeMessages}
      isStreaming={isStreaming}
      docFilterLabel={docFilterLabel}
      onSend={handleSend}
      onVoiceBeforeFirstUse={handleVoiceBeforeFirstUse}
    />
  );

  return (
    <div className="flex h-screen bg-background">
      <Sidebar
        conversations={sortedConversations.map((c) => ({ id: c.id, title: c.title }))}
        activeId={activeId}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
        onNewConversation={handleNewConversation}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={(id) => void handleDeleteConversation(id)}
        userEmail={user?.email}
        onLogout={handleLogout}
      />
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 overflow-y-auto">{mainView}</div>
        <AIDisclaimerFooter onOpenPrivacy={openPrivacy} />
      </div>

      <AIDisclaimerModal
        open={disclaimerOpen}
        onAcknowledge={handleAcknowledgeDisclaimer}
        onOpenPrivacy={openPrivacy}
      />

      <VoiceDisclosureModal
        open={voiceModalOpen}
        onAllow={handleVoiceAllow}
        onCancel={handleVoiceCancel}
        onOpenPrivacy={openPrivacy}
      />
    </div>
  );
}
