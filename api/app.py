"""
Conv-agent API: RAG chatbot over Italian electricity-grid regulatory PDFs.

Architecture: a top-level PydanticAI agent owns the conversation. It exposes
one tool, `search_regulations`, which wraps the retrieval + structured-answer
pipeline. The agent decides per turn whether to call the tool (for regulatory
questions) or reply directly (greetings, meta, acknowledgments). The grounding
constraint — never claim regulatory content from general knowledge — lives in
the top-level agent's system prompt.

  user msg ─▶ top-level agent ─┬─▶ direct reply (chit-chat, meta)
                               └─▶ search_regulations tool
                                     └─▶ retrieve + structured-answer
                                         └─▶ segments + sources

Endpoints:
  GET  /                  — service info
  GET  /health            — qdrant + collection liveness
  GET  /collection/info   — points count + per-doc breakdown
  POST /chat              — non-streaming, structured response
  POST /chat/stream       — SSE: meta, tool_call_start, tool_call_end,
                            segment, done, error
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Literal, Optional
from uuid import UUID, uuid4

# Logging + Sentry are configured BEFORE FastAPI is constructed so the
# integrations see every request from the first one onward.
from logging_setup import (  # noqa: E402
    configure_logging,
    conversation_id_var,
    get_logger,
    request_id_var,
)
from sentry_setup import configure_sentry  # noqa: E402

configure_logging()
_SENTRY_ON = configure_sentry()
log = get_logger("api")
log.info("api_starting", sentry_enabled=_SENTRY_ON)

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy.orm import Session

from auth.deps import current_user_required
from db import get_db
from db.models import Conversation as DBConversation, User as DBUser


# ---------- Configuration ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "conv_agent_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")

# Display titles per doc_id. Currently hardcoded because PDF Title metadata
# wasn't propagated through the chunker — easy to backfill later by reading
# pdf.metadata.Title at index time. Falls back to doc_id itself if unknown.
DOC_TITLES: dict[str, str] = {
    "celex_32017r1485_it_txt": "Regolamento (UE) 2017/1485 (SOGL)",
    "727-22tiad": "TIAD — Testo Integrato Autoconsumo Diffuso",
    "59": "Allegato A.43 — Specifiche Funzionali Generali (Sistema di Misura)",
}


def doc_title(doc_id: str) -> str:
    return DOC_TITLES.get(doc_id, doc_id)


# ---------- Pydantic models ----------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    # The new user message — server stores it, then appends to the conversation
    # history pulled from Postgres before running the agent.
    message: str = Field(..., min_length=1, max_length=10000, description="The user's new question.")
    # If omitted, a fresh conversation is created and its id is returned in
    # the response (or the `done` SSE event). On subsequent turns the client
    # passes the id back.
    conversation_id: Optional[UUID] = Field(default=None, description="Existing conversation to append to. Omit to start a new one.")
    # Optional retrieval filter.
    doc_id: Optional[str] = Field(default=None, description="Restrict retrieval to one document.")
    top_k_chunks: int = Field(default=30, ge=1, le=100, description="Chunks pulled from Qdrant before dedup.")
    top_n_articles: int = Field(default=6, ge=1, le=15, description="Distinct articles passed to the LLM.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Quali sono gli obblighi dei TSO in materia di controllo della tensione?",
                "top_k_chunks": 30,
                "top_n_articles": 6,
            }
        }
    }


class Source(BaseModel):
    doc_id: str
    doc_title: str
    section_kind: str
    section_number: str
    section_title: str
    section_path: str
    page_start: int
    page_end: int
    snippet: str
    score: Optional[float] = None


class SegmentWithCitations(BaseModel):
    text: str = Field(..., description="Segment prose; no inline citation markers")
    citations: List[int] = Field(..., description="1-indexed source numbers")


class ChatResponse(BaseModel):
    conversation_id: str = Field(..., description="Pass this back in the next /chat request to continue this conversation.")
    segments: List[SegmentWithCitations]
    sources: List[Source]
    related_articles: List[Source] = Field(default_factory=list, description="Retrieved but uncited articles")
    query: str = Field(..., description="The user's original question")
    rewritten_query: Optional[str] = Field(default=None, description="Self-contained query the tool ran; differs from `query` only when the agent rewrote it.")


class HealthResponse(BaseModel):
    status: str
    qdrant_connected: bool
    collection_exists: bool
    points_count: Optional[int] = None


# ---------- Structured-output schema (what the LLM fills) ----------
class AnswerSegment(BaseModel):
    text: str = Field(description="A coherent paragraph (2-4 sentences) that forms part of the answer")
    cited_sources: List[int] = Field(
        description="1-indexed source numbers cited by this segment. Empty if no source supports it."
    )


class RAGResponse(BaseModel):
    segments: List[AnswerSegment]


# ---------- Prompts ----------
# Inner prompt: used by the `search_regulations` tool's structured-answer
# generator. The strict "no general knowledge fallback" rule lives here because
# this prompt only ever sees retrieved sources.
INNER_RAG_PROMPT = (
    "You are an expert assistant for Italian and European electricity-grid "
    "regulations. Use ONLY the provided source documents to answer.\n\n"

    "LANGUAGE — NON-NEGOTIABLE: Answer in the SAME language as the user's "
    "question. The 'Answer language' line in the user message tells you which. "
    "If sources are in Italian and the answer must be in English, translate. "
    "Never mix languages.\n\n"

    "STRUCTURE: 3-6 segments. Each segment is a paragraph of 2-4 sentences. "
    "Cover definitions, obligations, procedures, and references when relevant. "
    "Quote source text verbatim (with quotation marks) for definitions and "
    "regulatory obligations — paraphrasing legal text is risky.\n\n"

    "CITATIONS: For each segment, list the source numbers used in cited_sources "
    "(1-indexed). Cite only what the sources EXPLICITLY support. Cite multiple "
    "sources together when they support the same claim.\n\n"

    "NO FALLBACK TO GENERAL KNOWLEDGE: If the provided sources don't cover the "
    "question, emit ONE segment with cited_sources=[] whose text says exactly "
    "(in the answer language): 'Non trovo questa informazione nei documenti "
    "indicizzati.' / 'I can't find this information in the indexed documents.' "
    "Do NOT improvise an answer from general knowledge.\n\n"

    "TEXT FIELD: prose only. No '[1]', '(fonte 1)', '[Source 2]' inside text — "
    "citations go ONLY in cited_sources."
)


# Top-level agent prompt: owns the conversation, decides per turn whether to
# call the search tool or reply directly. The grounding rule is the load-
# bearing part — without it the agent will happily improvise regulatory
# claims from its training data.
TOP_AGENT_PROMPT = (
    "Sei conv-agent, un assistente per i regolamenti elettrici italiani ed "
    "europei. Hai a disposizione uno strumento, `search_regulations`, che "
    "cerca nei documenti indicizzati e produce una risposta strutturata con "
    "citazioni.\n\n"

    "USA LO STRUMENTO per:\n"
    "- Qualsiasi domanda sostanziale sui regolamenti (articoli, paragrafi, "
    "procedure, definizioni, obblighi).\n"
    "- Quando l'utente cita uno specifico articolo o regolamento.\n"
    "- Domande in stile \"come funziona X\", \"cosa prevede Y\", \"quali "
    "sono gli obblighi di Z\".\n\n"

    "RISPONDI DIRETTAMENTE (senza chiamare lo strumento) per:\n"
    "- Saluti (\"ciao\", \"salve\", \"hi\", \"buongiorno\") → risposta "
    "amichevole; ricorda all'utente che puoi aiutarlo con i regolamenti.\n"
    "- Meta-domande (\"cosa sai fare?\", \"chi sei?\", \"quali documenti "
    "hai?\") → spiega le tue capacità e elenca i tre documenti indicizzati: "
    "(1) Regolamento (UE) 2017/1485 — SOGL, "
    "(2) TIAD — Testo Integrato Autoconsumo Diffuso (ARERA 727/2022), "
    "(3) Allegato A.43 — Specifiche Funzionali del Sistema di Misura.\n"
    "- Ringraziamenti (\"grazie\", \"ok\", \"perfetto\") → risposta breve.\n"
    "- Richieste di chiarimento sulla tua risposta precedente — usa la "
    "cronologia, non chiamare di nuovo lo strumento.\n\n"

    "REGOLA DI ANCORAGGIO — FONDAMENTALE:\n"
    "- Non affermare MAI contenuti normativi dalla tua conoscenza generale.\n"
    "- Per qualsiasi affermazione su regolamenti, articoli, obblighi: "
    "CHIAMA LO STRUMENTO.\n"
    "- La risposta dello strumento viene mostrata direttamente all'utente; "
    "dopo aver chiamato lo strumento, rispondi con una breve conferma "
    "(es. \"Ecco quanto previsto.\") — il tuo testo dopo la chiamata "
    "non verrà mostrato all'utente.\n\n"

    "LINGUA: rispondi nella stessa lingua dell'utente. Default italiano se "
    "ambiguo."
)


# ---------- Citation cleanup ----------
# Strip inline markers like [1], (1, 2), [fonte 1], [Source 2] from segment text.
_CITATION_PATTERN = re.compile(
    r"\s*[\[\(](?:fonte\s*|source\s*|mascia\s*)?\d+(?:\s*[,،]\s*\d+)*[\]\)]\s*",
    re.IGNORECASE,
)


def _clean_text(text: str) -> str:
    cleaned = _CITATION_PATTERN.sub(" ", text or "").strip()
    return re.sub(r"\s+", " ", cleaned)


# ---------- Language detection ----------
# Italian function-word markers — short, common, and unlikely to appear in
# English in such density. We include leading/trailing spaces to avoid
# partial-word matches (' di ' vs 'dictionary').
_ITALIAN_MARKERS = (
    " il ", " lo ", " la ", " i ", " gli ", " le ",
    " di ", " del ", " dello ", " della ", " dei ", " degli ", " delle ",
    " che ", " sono ", " quali ", " quale ", " come ",
    " nel ", " nella ", " per ", " con ", " sul ", " sulla ",
    " un ", " una ", " uno ",
)

_ENGLISH_MARKERS = (
    " the ", " is ", " are ", " of ", " and ", " in ", " on ", " for ",
    " with ", " what ", " which ", " how ", " to ", " from ", " by ",
)


def _detect_answer_language(text: str) -> str:
    """Pick a language label for the LLM prompt.

    Strategy: check diacritics first (cheap and decisive when present), then
    fall back to common function-word counts. Italian regulatory text often
    has no accented characters in a given query ("Quali sono gli obblighi..."),
    so a diacritic-only detector wrongly classifies it as English.
    """
    if not text:
        return "Italian"

    arabic = sum(1 for c in text if "؀" <= c <= "ۿ")
    if arabic > 0:
        return "Arabic"

    # Italian-specific diacritics are decisive.
    if any(c in text for c in "àèéìòù"):
        return "Italian"
    # French markers (subset that doesn't overlap with Italian).
    if any(c in text for c in "êëâïôûçœ"):
        return "French"

    padded = " " + text.lower() + " "
    italian = sum(1 for m in _ITALIAN_MARKERS if m in padded)
    english = sum(1 for m in _ENGLISH_MARKERS if m in padded)

    if english > italian:
        return "English"
    # Default for this project (Italian regulation chatbot).
    return "Italian"


# ---------- Global state ----------
qdrant_client: Optional[QdrantClient] = None
openai_client: Optional[OpenAI] = None
ready = False


# Swagger UI auto-fills Optional[str] fields with the literal "string" when
# users hit "Try it out". Treat those as "not provided" so we don't ship
# nonsense filters that match zero documents.
_PLACEHOLDER_VALUES = {"string"}


def _is_placeholder(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _PLACEHOLDER_VALUES
    if isinstance(value, list):
        return all(_is_placeholder(v) for v in value) if value else False
    return False


# ---------- Retrieval + dedup ----------
def _embed(text: str) -> list[float]:
    assert openai_client is not None
    resp = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
    return resp.data[0].embedding


def _hit_to_source(hit) -> Source:
    meta = hit.payload.get("metadata", {})
    page_content = hit.payload.get("page_content", "")
    return Source(
        doc_id=meta.get("doc_id", ""),
        doc_title=doc_title(meta.get("doc_id", "")),
        section_kind=meta.get("section_kind", ""),
        section_number=meta.get("section_number", ""),
        section_title=meta.get("section_title", ""),
        section_path=meta.get("section_path", ""),
        page_start=meta.get("page_start", 0),
        page_end=meta.get("page_end", 0),
        snippet=page_content[:400],
        score=float(hit.score) if hit.score is not None else None,
    )


def _retrieve(
    query: str,
    top_k_chunks: int,
    top_n_articles: int,
    qdrant_filter: Optional[qmodels.Filter],
) -> tuple[list, list]:
    """Return (selected_hits, related_hits).

    selected_hits: deduped one-per-article hits we'll feed to the LLM.
    related_hits: the remaining article-level dedup leftovers — they didn't
    win their article slot but came up in retrieval, so we surface them as
    'Articoli correlati' in the response.
    """
    assert qdrant_client is not None
    qvec = _embed(query)
    raw_hits = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=qvec,
        limit=top_k_chunks,
        query_filter=qdrant_filter,
        with_payload=True,
    )

    # Group by (doc_id, kind, number), keep the highest-scoring chunk per article.
    by_article: dict[tuple, object] = {}
    for h in raw_hits:
        meta = h.payload.get("metadata", {})
        key = (meta.get("doc_id"), meta.get("section_kind"), meta.get("section_number"))
        prev = by_article.get(key)
        if prev is None or h.score > prev.score:
            by_article[key] = h

    ordered = sorted(by_article.values(), key=lambda h: -h.score)
    selected = ordered[:top_n_articles]
    related = ordered[top_n_articles:top_n_articles + 5]  # show up to 5 related
    return selected, related


def _format_sources_for_llm(hits: list) -> str:
    """Numbered source block fed into the LLM context."""
    parts = []
    for i, h in enumerate(hits, 1):
        meta = h.payload.get("metadata", {})
        header = (
            f"[Source {i}] — {doc_title(meta.get('doc_id', ''))}, "
            f"{meta.get('section_kind', '')} {meta.get('section_number', '')}"
        )
        if meta.get("section_path"):
            header += f" ({meta['section_path']})"
        header += f", pages {meta.get('page_start')}-{meta.get('page_end')}"
        body = h.payload.get("page_content", "")
        parts.append(f"{header}\n{body}")
    return "\n\n---\n\n".join(parts)


# ---------- LLM builders ----------
_inner_rag_agent_singleton = None


def _get_inner_rag_agent():
    """Lazy-init the pydantic-ai agent that the `search_regulations` tool uses
    internally for structured-output streaming. Returns a `RAGResponse` shape."""
    global _inner_rag_agent_singleton
    if _inner_rag_agent_singleton is not None:
        return _inner_rag_agent_singleton
    _inner_rag_agent_singleton = Agent(
        f"openai:{LLM_MODEL}",
        result_type=RAGResponse,
        system_prompt=INNER_RAG_PROMPT,
    )
    return _inner_rag_agent_singleton


# ---------- Top-level agent + search tool ----------
# Deps passed through the agent loop into the tool. The tool uses `emit` to
# push SSE events back to the endpoint's generator; it stores retrieval
# results so the endpoint can assemble the final `done` payload.
@dataclass
class AgentDeps:
    doc_id_filter: Optional[str]
    emit: Callable[[str, dict], Awaitable[None]]
    http_request: Optional[Request] = None
    # Set by the search_regulations tool when called:
    tool_called: bool = False
    tool_query: Optional[str] = None
    tool_doc_id: Optional[str] = None
    tool_selected: Optional[list] = None
    tool_related: Optional[list] = None
    tool_raw_to_new: Optional[dict] = None


async def _search_and_stream_segments(
    query: str,
    doc_id_filter: Optional[str],
    emit: Callable[[str, dict], Awaitable[None]],
    http_request: Optional[Request] = None,
) -> Optional[tuple[list, list, dict]]:
    """Retrieval + structured streaming. Emits `segment` events via `emit`.

    Returns (selected, related, raw_to_new) on hit, or None when retrieval
    came back empty (caller emits the 'I can't find this' segment).
    """
    qdrant_filter = None
    if doc_id_filter and not _is_placeholder(doc_id_filter):
        qdrant_filter = qmodels.Filter(must=[
            qmodels.FieldCondition(
                key="metadata.doc_id",
                match=qmodels.MatchValue(value=doc_id_filter),
            )
        ])

    selected, related = await asyncio.to_thread(_retrieve, query, 30, 6, qdrant_filter)
    if not selected:
        return None

    answer_language = _detect_answer_language(query)
    user_message = (
        f"Answer language: {answer_language}\n\n"
        f"Sources:\n{_format_sources_for_llm(selected)}\n\n"
        f"Question: {query}\n\n"
        f"Reminder: your entire answer must be written in {answer_language}."
    )

    inner_agent = _get_inner_rag_agent()
    segment_buffers: list[dict] = []
    raw_to_new: dict[int, int] = {}
    next_new_idx = 1

    def _process_partial(partial) -> list[int]:
        segs = getattr(partial, "segments", None) or []
        while len(segment_buffers) < len(segs):
            segment_buffers.append({"text": "", "cited_sources": [], "emitted": False})
        for i, seg in enumerate(segs):
            if seg.text and seg.text != segment_buffers[i]["text"]:
                segment_buffers[i]["text"] = seg.text
            if seg.cited_sources:
                segment_buffers[i]["cited_sources"] = list(seg.cited_sources)
        return [i for i in range(len(segs) - 1) if not segment_buffers[i]["emitted"]]

    def _build_segment_payload(idx: int) -> dict:
        nonlocal next_new_idx
        buf = segment_buffers[idx]
        buf["emitted"] = True
        new_citations: list[int] = []
        for raw_idx in buf["cited_sources"]:
            if not (1 <= raw_idx <= len(selected)):
                continue
            if raw_idx not in raw_to_new:
                raw_to_new[raw_idx] = next_new_idx
                next_new_idx += 1
            new_citations.append(raw_to_new[raw_idx])
        return {
            "index": idx,
            "text": _clean_text(buf["text"]),
            "citations": new_citations,
        }

    async with inner_agent.run_stream(user_message) as result:
        async for message, is_last in result.stream_structured(debounce_by=None):
            if http_request is not None and await http_request.is_disconnected():
                return selected, related, raw_to_new
            try:
                partial = await result.validate_structured_result(
                    message, allow_partial=not is_last,
                )
            except Exception:
                continue
            for idx in _process_partial(partial):
                await emit("segment", _build_segment_payload(idx))
        for idx in range(len(segment_buffers)):
            if not segment_buffers[idx]["emitted"]:
                await emit("segment", _build_segment_payload(idx))

    return selected, related, raw_to_new


_top_agent_singleton = None


def _get_top_agent():
    """Lazy-init the top-level pydantic-ai agent that owns the conversation
    and decides per-turn whether to call `search_regulations` or reply
    directly to chit-chat / meta-questions."""
    global _top_agent_singleton
    if _top_agent_singleton is not None:
        return _top_agent_singleton

    agent = Agent(
        f"openai:{LLM_MODEL}",
        deps_type=AgentDeps,
        system_prompt=TOP_AGENT_PROMPT,
    )

    @agent.tool
    async def search_regulations(
        ctx: RunContext[AgentDeps],
        query: str,
        doc_id: Optional[str] = None,
    ) -> str:
        """Cerca nei regolamenti elettrici italiani ed europei indicizzati e
        produce una risposta strutturata con citazioni.

        Usa questo strumento per qualsiasi domanda sostanziale sui regolamenti.
        L'utente vedrà direttamente la risposta strutturata; tu riceverai solo
        una breve conferma testuale.

        Args:
            query: Una query autosufficiente per la ricerca semantica, nella
              lingua dell'utente (italiano per default). Integra il contesto
              dalla cronologia se necessario.
            doc_id: Restringi la ricerca a un documento specifico. Valori
              ammessi: 'celex_32017r1485_it_txt' (SOGL Reg. UE 2017/1485),
              '727-22tiad' (TIAD autoconsumo ARERA),
              '59' (Allegato A.43 Sistema di Misura).
              Lascia vuoto per cercare in tutti i documenti.
        """
        deps = ctx.deps
        deps.tool_called = True
        deps.tool_query = query
        effective_doc_id = doc_id or deps.doc_id_filter
        deps.tool_doc_id = effective_doc_id

        await deps.emit("tool_call_start", {
            "query": query,
            "doc_id": effective_doc_id,
        })

        result = await _search_and_stream_segments(
            query=query,
            doc_id_filter=effective_doc_id,
            emit=deps.emit,
            http_request=deps.http_request,
        )

        if result is None:
            await deps.emit("tool_call_end", {"n_sources": 0, "n_articles": 0})
            return "Nessun articolo rilevante trovato nei documenti indicizzati."

        selected, related, raw_to_new = result
        deps.tool_selected = selected
        deps.tool_related = related
        deps.tool_raw_to_new = raw_to_new

        await deps.emit("tool_call_end", {
            "n_sources": len(raw_to_new),
            "n_articles": len(selected),
        })

        return (
            f"Ricerca completata: {len(selected)} articoli recuperati, "
            f"{len(raw_to_new)} citati. La risposta strutturata è già stata "
            "mostrata all'utente."
        )

    _top_agent_singleton = agent
    return agent


def _build_agent_user_prompt(messages: List[ChatMessage]) -> str:
    """Flatten conversation history + latest question into a single prompt
    for the top-level agent. (pydantic-ai 0.0.13's message_history API varies
    between minor versions; flattening into one user message is portable.)"""
    latest = messages[-1].content
    history = messages[:-1]
    if not history:
        return latest
    transcript = "\n".join(f"{m.role}: {m.content}" for m in history)
    return (
        f"Cronologia conversazione:\n{transcript}\n\n"
        f"Nuovo messaggio dell'utente: {latest}"
    )


# ---------- DB helpers for the chat endpoints ----------
def _resolve_conversation(
    db: "Session",
    user: "DBUser",
    request: ChatRequest,
) -> "DBConversation":
    """Load (and ownership-check) an existing conversation, or create a new
    one. New conversations get their title derived from the user's first
    message; existing ones keep theirs."""
    from db.base import utcnow
    from db.models import Conversation as DBConversation

    if request.conversation_id is not None:
        conv = db.get(DBConversation, request.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="conversation not found")
        # Per-request doc_id overrides the conversation's stored filter for
        # this turn (we don't mutate the stored one — that's a PATCH job).
        return conv

    title = request.message.strip().replace("\n", " ")
    if len(title) > 60:
        title = title[:60].rstrip() + "…"
    conv = DBConversation(
        user_id=user.id,
        title=title or "Nuova conversazione",
        doc_filter=request.doc_id,
        updated_at=utcnow(),
    )
    db.add(conv)
    db.flush()  # ensure conv.id is populated before we tag messages with it
    return conv


def _persist_user_message(db: "Session", conv: "DBConversation", text: str) -> None:
    from db.base import utcnow
    from db.models import Message as DBMessage

    db.add(DBMessage(conversation_id=conv.id, role="user", content=text))
    conv.updated_at = utcnow()
    db.flush()


def _flatten_assistant_text(payload: Optional[dict]) -> str:
    """Reconstruct the plain prose an assistant message produced.

    Used when feeding history back into the agent — the rewriter wants
    text, not the structured payload.
    """
    if not payload:
        return ""
    segs = payload.get("segments") or []
    return "\n\n".join((s.get("text") or "") for s in segs)


def _load_history_as_chat_messages(
    db: "Session",
    conv: "DBConversation",
) -> List[ChatMessage]:
    """Pull every prior message for this conversation in chronological order
    and convert to the `ChatMessage` shape the agent expects."""
    from sqlalchemy import select
    from db.models import Message as DBMessage

    rows = db.execute(
        select(DBMessage)
        .where(DBMessage.conversation_id == conv.id)
        .order_by(DBMessage.created_at)
    ).scalars().all()

    out: List[ChatMessage] = []
    for m in rows:
        if m.role == "user":
            out.append(ChatMessage(role="user", content=m.content))
        elif m.role == "assistant":
            text = _flatten_assistant_text(m.payload) or m.content
            out.append(ChatMessage(role="assistant", content=text))
    return out


def _persist_assistant_and_audit(
    db: "Session",
    user: "DBUser",
    conv: "DBConversation",
    request: ChatRequest,
    http_request: Request,
    segments: List[dict],
    sources: List[dict],
    related_articles: List[dict],
    deps: Optional["AgentDeps"],
    agent_mode: str,
    latency_ms: int,
) -> None:
    """Write the assistant message + audit log row atomically after a chat
    completion. Run inside the request session — caller is expected to commit."""
    from db.base import utcnow
    from db.models import Message as DBMessage, QALog as DBQALog

    joined_text = "\n\n".join(s.get("text", "") for s in segments)

    tool_payload = None
    rewritten_query = None
    doc_id_filter = request.doc_id
    retrieved_chunk_ids: list[str] = []

    if deps is not None and deps.tool_called:
        rewritten_query = deps.tool_query
        doc_id_filter = deps.tool_doc_id or doc_id_filter
        tool_payload = {
            "query": deps.tool_query,
            "doc_id": deps.tool_doc_id,
            "n_sources": len(deps.tool_raw_to_new) if deps.tool_raw_to_new else 0,
            "n_articles": len(deps.tool_selected) if deps.tool_selected else 0,
        }
        if deps.tool_selected:
            for hit in deps.tool_selected:
                pid = getattr(hit, "id", None)
                if pid is not None:
                    retrieved_chunk_ids.append(str(pid))

    assistant_payload = {
        "segments": segments,
        "sources": sources,
        "related_articles": related_articles,
        "toolCall": tool_payload,
    }
    db.add(
        DBMessage(
            conversation_id=conv.id,
            role="assistant",
            content=joined_text,
            payload=assistant_payload,
        )
    )

    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    db.add(
        DBQALog(
            user_id=user.id,
            conversation_id=conv.id,
            query=request.message,
            rewritten_query=rewritten_query,
            doc_id_filter=doc_id_filter,
            retrieved_chunk_ids=retrieved_chunk_ids or None,
            sources_returned={"sources": sources, "related": related_articles},
            agent_mode=agent_mode,
            llm_model=LLM_MODEL,
            latency_ms=latency_ms,
            client_ip=client_ip,
            user_agent=(user_agent[:500] if user_agent else None),
        )
    )

    conv.updated_at = utcnow()


# ---------- Lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global qdrant_client, openai_client, ready

    log.info("api_lifespan_start")
    if not OPENAI_API_KEY:
        log.error("openai_key_missing")

    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    qdrant_client = QdrantClient(url=QDRANT_URL, timeout=60)

    if not qdrant_client.collection_exists(COLLECTION_NAME):
        log.warning("qdrant_collection_missing", collection=COLLECTION_NAME)
        ready = False
    else:
        info = qdrant_client.get_collection(COLLECTION_NAME)
        log.info("api_ready", collection=COLLECTION_NAME, points=info.points_count)
        ready = True

    yield

    log.info("api_lifespan_stop")


# ---------- App ----------
app = FastAPI(
    title="conv-agent",
    description="RAG chatbot for Italian electricity-grid regulations",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS lockdown — replace wildcards with an env-driven allowlist. Browsers
# reject credentialed requests against `*` origins anyway, so this is both
# a correctness fix and a defense-in-depth one.
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,  # cache preflights for 10 minutes
)


# Per-request log context: every log line during a request includes a
# request_id (from incoming X-Request-ID header, or one we mint), and the
# user_id once `current_user_required` resolves. The id is echoed back in
# the response so a client can correlate a complaint with backend logs.
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    rid = (request.headers.get("X-Request-ID") or uuid4().hex[:12])[:64]
    rid_token = request_id_var.set(rid)
    cid_token = conversation_id_var.set(None)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(rid_token)
        conversation_id_var.reset(cid_token)

# Rate limiter — used as a FastAPI Depends on protected endpoints. See
# api/rate_limit.py for the sliding-window implementation.
from rate_limit import chat_rate_limit, transcribe_rate_limit  # noqa: E402

# Routers: auth + conversation CRUD.
from auth.router import router as auth_router  # noqa: E402
from conversations import router as conversations_router  # noqa: E402

app.include_router(auth_router)
app.include_router(conversations_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "conv-agent",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    if qdrant_client is None:
        return HealthResponse(status="unhealthy", qdrant_connected=False, collection_exists=False)
    try:
        exists = qdrant_client.collection_exists(COLLECTION_NAME)
        points = None
        if exists:
            points = qdrant_client.get_collection(COLLECTION_NAME).points_count
        return HealthResponse(
            status="healthy" if exists else "degraded",
            qdrant_connected=True,
            collection_exists=exists,
            points_count=points,
        )
    except Exception:
        return HealthResponse(status="unhealthy", qdrant_connected=False, collection_exists=False)


@app.get("/collection/info", tags=["Collection"])
async def collection_info():
    if qdrant_client is None or not qdrant_client.collection_exists(COLLECTION_NAME):
        raise HTTPException(404, f"collection '{COLLECTION_NAME}' not found")

    info = qdrant_client.get_collection(COLLECTION_NAME)

    # Per-doc point breakdown via scroll. Cheap on small corpora (a few hundred
    # to a few thousand points); for big collections we'd want a faceted query.
    by_doc: dict[str, int] = {}
    next_offset = None
    while True:
        points, next_offset = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            with_payload=["metadata"],
            with_vectors=False,
            offset=next_offset,
        )
        for p in points:
            doc_id = p.payload.get("metadata", {}).get("doc_id", "?")
            by_doc[doc_id] = by_doc.get(doc_id, 0) + 1
        if next_offset is None:
            break

    return {
        "collection_name": COLLECTION_NAME,
        "points_count": info.points_count,
        "status": str(info.status),
        "by_doc": [
            {"doc_id": d, "doc_title": doc_title(d), "chunks": c}
            for d, c in sorted(by_doc.items(), key=lambda x: -x[1])
        ],
    }


# ---------- /chat (non-streaming, drives the agent) ----------
# slowapi locates the Request via type annotation — `http_request: Request`
# satisfies it without needing a parameter literally named `request`.
@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(
    request: ChatRequest,
    http_request: Request,
    user: "DBUser" = Depends(current_user_required),
    db: "Session" = Depends(get_db),
    _rl: None = Depends(chat_rate_limit),
):
    if not ready:
        raise HTTPException(503, "RAG system not initialized — start qdrant and run the indexer first")

    t_start = time.time()

    # Resolve or create the conversation, then persist the new user message
    # so the history we feed into the agent reflects it.
    conv = _resolve_conversation(db, user, request)
    conversation_id_var.set(str(conv.id))
    _persist_user_message(db, conv, request.message)
    history = _load_history_as_chat_messages(db, conv)

    # Collect segments instead of streaming them out. tool_call_start /
    # tool_call_end aren't meaningful for non-streaming clients.
    collected_segments: list[dict] = []

    async def collect_emit(evt: str, data: dict) -> None:
        if evt == "segment":
            collected_segments.append(data)

    doc_id_in = request.doc_id if request.doc_id and not _is_placeholder(request.doc_id) else conv.doc_filter
    deps = AgentDeps(
        doc_id_filter=doc_id_in,
        emit=collect_emit,
        http_request=None,
    )

    top_agent = _get_top_agent()
    user_prompt = _build_agent_user_prompt(history)

    try:
        result = await top_agent.run(user_prompt, deps=deps)
    except Exception as e:
        # Persist a stub assistant message + audit row so the conversation
        # isn't silently truncated (the user message is already in DB).
        _persist_assistant_and_audit(
            db, user, conv, request, http_request,
            segments=[{"text": f"errore: {e}", "citations": []}],
            sources=[],
            related_articles=[],
            deps=None,
            agent_mode="error",
            latency_ms=int((time.time() - t_start) * 1000),
        )
        db.commit()
        raise HTTPException(500, f"agent error: {e}")

    total = time.time() - t_start
    sources_out: list[dict] = []
    related_out: list[dict] = []
    response_segments: list[SegmentWithCitations] = []
    agent_mode = "direct"

    if deps.tool_called:
        if deps.tool_selected is None or deps.tool_raw_to_new is None:
            agent_mode = "tool_empty"
            response_segments = [SegmentWithCitations(
                text="Non trovo questa informazione nei documenti indicizzati.",
                citations=[],
            )]
        else:
            agent_mode = "tool_used"
            cited_in_order = sorted(deps.tool_raw_to_new.keys(), key=lambda r: deps.tool_raw_to_new[r])
            sources_out = [_hit_to_source(deps.tool_selected[r - 1]).model_dump() for r in cited_in_order]
            cited_set = set(deps.tool_raw_to_new.keys())
            unused = [h for i, h in enumerate(deps.tool_selected, 1) if i not in cited_set]
            related_out = [_hit_to_source(h).model_dump() for h in unused + (deps.tool_related or [])]
            if not sources_out:
                related_out = []
            response_segments = [
                SegmentWithCitations(text=s["text"], citations=s["citations"])
                for s in collected_segments
            ]
    else:
        # Direct reply (chit-chat / meta).
        direct_text = _clean_text(result.data or "")
        response_segments = [SegmentWithCitations(text=direct_text, citations=[])]

    # Persist assistant + audit, commit once.
    _persist_assistant_and_audit(
        db, user, conv, request, http_request,
        segments=[s.model_dump() for s in response_segments],
        sources=sources_out,
        related_articles=related_out,
        deps=deps,
        agent_mode=agent_mode,
        latency_ms=int(total * 1000),
    )
    db.commit()

    log.info(
        "chat_complete",
        mode=agent_mode,
        latency_ms=int(total * 1000),
        segments=len(response_segments),
        sources=len(sources_out),
        doc_id=deps.tool_doc_id or request.doc_id,
    )

    return ChatResponse(
        conversation_id=str(conv.id),
        segments=response_segments,
        sources=[Source(**s) for s in sources_out],
        related_articles=[Source(**s) for s in related_out],
        query=request.message,
        rewritten_query=(
            deps.tool_query if deps.tool_query and deps.tool_query != request.message else None
        ),
    )


# ---------- SSE helpers ----------
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"


# ---------- /chat/stream (drives the agent + tool, emits SSE) ----------
@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    user: DBUser = Depends(current_user_required),
    db: Session = Depends(get_db),
    _rl: None = Depends(chat_rate_limit),
):
    """
    Agent-driven streaming endpoint.

    SSE events:
      meta              — `{mode: "pending", conversation_id}` (the id is
                          known up-front so the client can persist it
                          immediately even if the stream is later interrupted).
      tool_call_start   — agent invoked search_regulations; `{query, doc_id}`.
      tool_call_end     — search finished; `{n_sources, n_articles}`.
      segment           — emitted by the search tool's structured streamer,
                          OR (for direct replies) a single segment after the
                          agent finishes.
      done              — terminal: `{sources, related_articles, query, conversation_id}`.
      error             — on any unhandled exception.
    """
    if not ready:
        raise HTTPException(503, "RAG system not initialized")

    # Resolve / create conversation + persist the user turn BEFORE we start
    # the stream — that way the conversation_id is in the meta event and the
    # history we feed the agent reflects this turn.
    conv = _resolve_conversation(db, user, request)
    conversation_id_var.set(str(conv.id))
    _persist_user_message(db, conv, request.message)
    history = _load_history_as_chat_messages(db, conv)
    db.commit()  # release this transaction; we'll write the assistant turn
    # later in another transaction.

    conv_id_str = str(conv.id)

    async def event_generator():
        t_start = time.time()

        # Async queue that the tool emits SSE events through.
        queue: asyncio.Queue = asyncio.Queue()
        DONE = object()  # sentinel signaling the agent has finished

        async def emit(evt: str, data: dict) -> None:
            await queue.put((evt, data))

        doc_id_in = request.doc_id if request.doc_id and not _is_placeholder(request.doc_id) else conv.doc_filter
        deps = AgentDeps(
            doc_id_filter=doc_id_in,
            emit=emit,
            http_request=http_request,
        )

        agent_text_holder: list[str] = []
        agent_error_holder: list[str] = []
        # Capture every segment the tool emits, so we can persist the full
        # assistant payload to Postgres after the stream completes.
        collected_segments: list[dict] = []

        async def run_agent() -> None:
            try:
                top_agent = _get_top_agent()
                user_prompt = _build_agent_user_prompt(history)
                result = await top_agent.run(user_prompt, deps=deps)
                agent_text_holder.append(result.data or "")
            except Exception as e:
                import traceback
                traceback.print_exc()
                agent_error_holder.append(str(e))
            finally:
                await queue.put(DONE)

        agent_task = asyncio.create_task(run_agent())

        yield _sse("meta", {"mode": "pending", "conversation_id": conv_id_str})

        # Drain emitted events as they arrive. Mirror segments into the
        # collector for later DB write.
        try:
            while True:
                item = await queue.get()
                if item is DONE:
                    break
                evt, data = item
                if evt == "segment":
                    collected_segments.append(data)
                yield _sse(evt, data)
        finally:
            if not agent_task.done():
                await agent_task

        latency_ms = int((time.time() - t_start) * 1000)

        if agent_error_holder:
            _persist_assistant_and_audit(
                db, user, conv, request, http_request,
                segments=[{"text": f"errore: {agent_error_holder[0]}", "citations": []}],
                sources=[],
                related_articles=[],
                deps=None,
                agent_mode="error",
                latency_ms=latency_ms,
            )
            db.commit()
            yield _sse("error", {"detail": agent_error_holder[0]})
            return

        sources_out: list[dict] = []
        related_out: list[dict] = []
        agent_mode = "direct"

        if deps.tool_called:
            if deps.tool_selected is None or deps.tool_raw_to_new is None:
                # Tool was invoked but retrieval was empty.
                empty_seg = {
                    "index": 0,
                    "text": "Non trovo questa informazione nei documenti indicizzati.",
                    "citations": [],
                }
                collected_segments.append(empty_seg)
                yield _sse("segment", empty_seg)
                agent_mode = "tool_empty"
            else:
                agent_mode = "tool_used"
                cited_in_order = sorted(deps.tool_raw_to_new.keys(), key=lambda r: deps.tool_raw_to_new[r])
                sources_out = [_hit_to_source(deps.tool_selected[r - 1]).model_dump() for r in cited_in_order]
                cited_set = set(deps.tool_raw_to_new.keys())
                unused = [h for i, h in enumerate(deps.tool_selected, 1) if i not in cited_set]
                related_out = [_hit_to_source(h).model_dump() for h in unused + (deps.tool_related or [])]
                if not sources_out:
                    related_out = []
        else:
            # Direct reply path (chit-chat / meta). One segment with the agent's text.
            direct_text = _clean_text(agent_text_holder[0] if agent_text_holder else "")
            direct_seg = {"index": 0, "text": direct_text, "citations": []}
            collected_segments.append(direct_seg)
            yield _sse("segment", direct_seg)

        # Persist assistant + audit BEFORE the final done event, so a client
        # that immediately re-fetches /conversations/{id} sees a consistent view.
        _persist_assistant_and_audit(
            db, user, conv, request, http_request,
            segments=collected_segments,
            sources=sources_out,
            related_articles=related_out,
            deps=deps,
            agent_mode=agent_mode,
            latency_ms=latency_ms,
        )
        db.commit()

        yield _sse("done", {
            "sources": sources_out,
            "related_articles": related_out,
            "query": request.message,
            "conversation_id": conv_id_str,
        })

        log.info(
            "chat_stream_complete",
            mode=agent_mode,
            latency_ms=latency_ms,
            segments=len(collected_segments),
            sources=len(sources_out),
            doc_id=deps.tool_doc_id or request.doc_id,
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- /transcribe (speech to text) ----------
from transcription import (  # noqa: E402
    ACCEPTED_MIME_TYPES,
    TRANSCRIBE_MODEL,
    TranscriptionError,
    transcribe_audio,
)


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration_ms: int
    model: str


# Hard cap on audio size — server-side defense against someone uploading
# a 2-hour MP3 from a file picker (if/when we add that). The frontend's
# tap-to-toggle UI already caps recordings at 60s.
_MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8 MB


@app.post("/transcribe", response_model=TranscribeResponse, tags=["Voice"])
async def transcribe(
    http_request: Request,
    audio: UploadFile = File(...),
    user: DBUser = Depends(current_user_required),
    _rl: None = Depends(transcribe_rate_limit),
):
    """Transcribe a short audio recording (≤ 60s of speech) to text.

    Used by the mic button on the chat input. Returns plain text — the
    client either drops it into the input box for the user to edit, or
    posts it straight to /chat/stream.
    """
    if not ready:
        raise HTTPException(503, "transcription not available — service not initialized")

    content_type = (audio.content_type or "").lower().split(";", 1)[0].strip()
    if content_type and content_type not in ACCEPTED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"audio format '{content_type}' not supported",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "empty audio")
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large (max 8 MB)")

    t_start = time.time()
    try:
        result = await asyncio.to_thread(
            transcribe_audio,
            openai_client,
            audio_bytes,
            audio.filename or "audio.webm",
            content_type or "audio/webm",
        )
    except TranscriptionError as e:
        log.warning("transcribe_failed", error=str(e), bytes=len(audio_bytes))
        raise HTTPException(502, "transcription failed; try again")

    latency_ms = int((time.time() - t_start) * 1000)
    log.info(
        "transcribe_complete",
        bytes=len(audio_bytes),
        chars=len(result["text"]),
        latency_ms=latency_ms,
        language=result["language"],
    )

    return TranscribeResponse(
        text=result["text"],
        language=result["language"],
        duration_ms=latency_ms,
        model=TRANSCRIBE_MODEL,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
