"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowUp,
  ChevronDown,
  ChevronUp,
  FileText,
  Plus,
  Search,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { VoiceInputButton } from "./VoiceInputButton";
import type { AssistantMessage, Message, Source } from "@/types";

interface ConversationViewProps {
  messages: Message[];
  isStreaming: boolean;
  docFilterLabel: string;
  onSend: (text: string) => void;
  onVoiceBeforeFirstUse?: () => Promise<boolean>;
}

export function ConversationView({
  messages,
  isStreaming,
  docFilterLabel,
  onSend,
  onVoiceBeforeFirstUse,
}: ConversationViewProps) {
  const [inputValue, setInputValue] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new content. Watching messages.length covers user-sent
  // bubbles; watching the last assistant message's segment count covers
  // segments arriving via SSE.
  const lastAssistant = messages.findLast((m) => m.role === "assistant") as
    | AssistantMessage
    | undefined;
  const lastSegmentCount = lastAssistant?.payload.segments.length ?? 0;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, lastSegmentCount, isStreaming]);

  const handleSend = () => {
    const text = inputValue.trim();
    if (!text || isStreaming) return;
    onSend(text);
    setInputValue("");
  };

  return (
    // h-full (not min-h-screen) so this component is exactly the viewport
    // height. That lets <main> below be the real scroll container — auto-
    // scrolling new messages stays inside the messages region instead of
    // scrolling the outer page (which would land hidden behind the sticky
    // input bar).
    <div className="h-full flex flex-col bg-background overflow-hidden">
      {/* Brand strip across the very top */}
      <div aria-hidden className="h-[3px] bg-brand-strip" />

      {/* Header — labels the current scope (assistant + active doc filter).
          "Nuova conversazione" lives in the sidebar, so we don't duplicate it
          here. */}
      <header className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b border-border">
        <div className="px-6 py-4 flex flex-col leading-tight">
          <span className="text-[11px] tracking-wide uppercase text-muted-foreground">
            Assistente normativo
          </span>
          <span className="text-xs text-foreground/80">{docFilterLabel}</span>
        </div>
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          {messages.map((m) =>
            m.role === "user" ? (
              <UserBubble key={m.id} content={m.content} />
            ) : (
              <AssistantBubble key={m.id} message={m as AssistantMessage} />
            ),
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      {/* Input — floating widget. The gradient mask above fades the
          scrolling chat content into the background so it doesn't appear
          to slide under a hard rule, and the input sits on top with its
          own shadow. No top border on the wrapper. */}
      <div className="sticky bottom-0 z-10 pointer-events-none">
        <div
          aria-hidden
          className="h-8 bg-gradient-to-t from-background via-background/90 to-transparent"
        />
        <div className="bg-background pointer-events-auto px-4 pt-1 pb-4">
          <div className="max-w-3xl mx-auto">
            <div
              className={cn(
                "bg-card border border-border rounded-2xl shadow-[0_10px_30px_-12px_rgb(0_0_0/0.18)] flex items-end gap-2 p-2 transition-all",
                "focus-within:border-primary/40 focus-within:shadow-[0_14px_36px_-12px_rgb(0_0_0/0.22)]",
                isStreaming && "opacity-90",
              )}
            >
            <textarea
              ref={inputRef}
              placeholder={isStreaming ? "Risposta in corso..." : "Continua la conversazione..."}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none bg-transparent outline-none px-2 py-1.5 text-sm placeholder:text-muted-foreground max-h-40"
            />
            <button
              type="button"
              disabled
              title="Carica file (presto disponibile)"
              className="p-2 text-muted-foreground/40 cursor-not-allowed"
            >
              <Plus className="w-4 h-4" />
            </button>
            <VoiceInputButton
              disabled={isStreaming}
              onBeforeFirstUse={onVoiceBeforeFirstUse}
              onTranscribed={(text) =>
                setInputValue((v) => (v ? `${v.trim()} ${text}` : text))
              }
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={!inputValue.trim() || isStreaming}
              className={cn(
                "w-9 h-9 flex items-center justify-center rounded-full transition-all",
                inputValue.trim() && !isStreaming
                  ? "bg-primary text-primary-foreground hover:opacity-90 shadow-sm"
                  : "bg-secondary text-muted-foreground cursor-not-allowed",
              )}
            >
              <ArrowUp className="w-4 h-4" />
            </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- User bubble ----------
function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl bg-foreground text-background px-4 py-3 shadow-sm whitespace-pre-wrap text-sm leading-relaxed">
        {content}
      </div>
    </div>
  );
}

// ---------- Assistant bubble ----------
function AssistantBubble({ message }: { message: AssistantMessage }) {
  const { payload, streaming, error } = message;
  const hasContent = payload.segments.length > 0;
  const tool = payload.toolCall;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-start"
    >
      <div className="max-w-[90%] w-full space-y-3">
        {/* "Sto pensando..." pill — shown only when the agent is still
            deciding (streaming, no tool call started, no segments yet). */}
        {streaming && !tool && !hasContent && <ThinkingPill />}

        {/* Tool-call status pill — visible whenever the agent invoked the
            search tool, so users know whether the answer is grounded. */}
        {tool && <ToolCallPill tool={tool} />}

        {error && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/5 text-destructive text-sm px-4 py-3">
            Errore: {error}
          </div>
        )}

        {hasContent && (
          // Assistant prose renders as plain text on the background — no
          // surrounding card. Sources keep their card treatment below.
          <div className="space-y-3">
            {payload.segments.map((seg, idx) => (
              <p key={idx} className="text-sm leading-relaxed text-foreground">
                {seg.text}
                {seg.citations.length > 0 && (
                  <span className="ml-1 inline-flex gap-1 align-baseline">
                    {seg.citations.map((c) => (
                      <CitationChip key={c} n={c} />
                    ))}
                  </span>
                )}
              </p>
            ))}
            {streaming && (
              <div className="pt-1">
                <TypingDots />
              </div>
            )}
          </div>
        )}

        {!streaming && payload.sources.length > 0 && (
          <SourcesList sources={payload.sources} />
        )}

        {!streaming && payload.related_articles.length > 0 && (
          <RelatedList items={payload.related_articles} />
        )}
      </div>
    </motion.div>
  );
}

// ---------- Thinking pill (pre-tool, pre-segment) ----------
function ThinkingPill() {
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs border bg-secondary border-border text-muted-foreground w-fit"
    >
      <TypingDots />
      <span>Sto pensando...</span>
    </motion.div>
  );
}


// ---------- Tool-call pill ----------
const DOC_PILL_LABELS: Record<string, string> = {
  celex_32017r1485_it_txt: "SOGL",
  "727-22tiad": "TIAD",
  "59": "Sistema di Misura",
};

function ToolCallPill({
  tool,
}: {
  tool: NonNullable<AssistantMessage["payload"]["toolCall"]>;
}) {
  const docLabel = tool.doc_id ? DOC_PILL_LABELS[tool.doc_id] ?? tool.doc_id : null;
  const isRunning = tool.status === "running";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -2 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs border w-fit",
        isRunning
          ? "bg-primary/10 border-primary/20 text-primary"
          : "bg-secondary border-border text-muted-foreground",
      )}
    >
      <Search className={cn("w-3.5 h-3.5", isRunning && "animate-pulse")} />
      <span>
        {isRunning
          ? "Sto cercando nei regolamenti"
          : `Ricerca completata${tool.n_articles ? ` · ${tool.n_articles} articoli` : ""}`}
      </span>
      {docLabel && (
        <span
          className={cn(
            "ml-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium",
            isRunning
              ? "bg-primary/15 text-primary"
              : "bg-card text-muted-foreground border border-border",
          )}
        >
          {docLabel}
        </span>
      )}
    </motion.div>
  );
}


// ---------- Citation chip ----------
function CitationChip({ n }: { n: number }) {
  return (
    <a
      href={`#source-${n}`}
      onClick={(e) => {
        e.preventDefault();
        const el = document.getElementById(`source-${n}`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        el?.classList.add("ring-2", "ring-primary/50");
        setTimeout(() => el?.classList.remove("ring-2", "ring-primary/50"), 1200);
      }}
      className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-md bg-primary/10 text-primary text-[11px] font-semibold no-underline hover:bg-primary/15 transition-colors"
    >
      {n}
    </a>
  );
}

// ---------- Sources ----------
function SourcesList({ sources }: { sources: Source[] }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground px-1">
        Fonti citate
      </div>
      <div className="grid grid-cols-1 gap-2">
        {sources.map((s, i) => (
          <SourceCard key={`${s.doc_id}-${s.section_kind}-${s.section_number}`} index={i + 1} s={s} />
        ))}
      </div>
    </div>
  );
}

function SourceCard({ index, s }: { index: number; s: Source }) {
  const label =
    s.section_kind === "articolo"
      ? `Articolo ${s.section_number}`
      : s.section_kind === "allegato"
        ? `Allegato ${s.section_number}`
        : `Sezione ${s.section_number}`;
  const pages =
    s.page_start === s.page_end ? `p. ${s.page_start}` : `pp. ${s.page_start}-${s.page_end}`;
  return (
    <div
      id={`source-${index}`}
      className="rounded-xl border border-border bg-card p-3 transition-all"
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex items-center justify-center min-w-[24px] h-6 px-2 rounded-md bg-primary/10 text-primary text-xs font-semibold">
          {index}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <FileText className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
            <span className="text-xs text-muted-foreground truncate">{s.doc_title}</span>
          </div>
          <div className="text-sm font-medium text-foreground mt-0.5">
            {label}
            {s.section_title && <span className="text-muted-foreground"> — {s.section_title}</span>}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {s.section_path} · {pages}
          </div>
          {s.snippet && (
            <details className="mt-2">
              <summary className="text-xs text-primary cursor-pointer hover:underline list-none">
                Mostra estratto
              </summary>
              <div className="mt-1.5 rounded-md bg-secondary/40 text-xs text-foreground whitespace-pre-wrap px-3 py-2 max-h-40 overflow-y-auto">
                {s.snippet}
              </div>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- Related (collapsed by default) ----------
function RelatedList({ items }: { items: Source[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground transition-colors px-1"
      >
        {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        Articoli correlati ({items.length})
      </button>
      {open && (
        <div className="grid grid-cols-1 gap-2">
          {items.map((s, i) => (
            <div
              key={`rel-${s.doc_id}-${s.section_kind}-${s.section_number}-${i}`}
              className="rounded-xl border border-border bg-card/50 p-3"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground truncate">{s.doc_title}</span>
              </div>
              <div className="text-sm text-foreground mt-0.5">
                {s.section_kind === "articolo" ? "Articolo" : "Sezione"} {s.section_number}
                {s.section_title && <span className="text-muted-foreground"> — {s.section_title}</span>}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {s.section_path} · pp. {s.page_start}-{s.page_end}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Indicators ----------
function TypingDots() {
  return (
    <div className="flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-primary typing-dot" />
      <span className="w-1.5 h-1.5 rounded-full bg-primary typing-dot" />
      <span className="w-1.5 h-1.5 rounded-full bg-primary typing-dot" />
    </div>
  );
}

