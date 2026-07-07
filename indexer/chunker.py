"""
Section → Chunk transformation.

Two passes:
  1. Merge: drop heading-only parent sections (e.g. '3. DESCRIZIONE FUNZIONALE
     GENERALE' with no body); their hierarchical context survives because we
     prepend the full section path to every child chunk's embedding text.
  2. Split: sections over the token budget get sub-chunked on paragraph
     boundaries first, sentence boundaries as fallback, then hard-truncate
     as a last resort.

Each chunk carries the metadata Qdrant needs for filtering + the metadata
the frontend needs for showing 'where this came from'.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

import tiktoken

from cleanup import CleanedDoc
from structure import Section


# ---------- Config ----------
# Target chunk size (we aim for this) and hard cap (never exceed it). Italian
# is ~1.5-2x more tokens per word than English with cl100k_base, so 600 tokens
# ≈ 1500-2000 chars — a comfortable size for retrieval and for the LLM to read.
TARGET_TOKENS = 600
MAX_TOKENS = 800

# Sections shorter than this are heading-only parents (e.g. '3. DESCRIZIONE
# FUNZIONALE GENERALE'). They contribute via their children's section_path,
# not as standalone chunks.
PARENT_ONLY_CHAR_THRESHOLD = 150

# A trailing sub-chunk smaller than this gets merged back into its predecessor
# (when the merge fits under hard_max). Stops the packer from spitting out
# 30-token orphans whenever a section ends just after a chunk boundary.
MIN_TAIL_TOKENS = 120


# ---------- Tokenizer (matches text-embedding-3-large) ----------
_encoder: tiktoken.Encoding | None = None


def _enc() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    return len(_enc().encode(text))


# ---------- Output model ----------
@dataclass
class Chunk:
    chunk_id: str               # stable, deterministic — used as Qdrant point id
    doc_id: str
    doc_type: str               # 'articolo' | 'numbered'
    section_kind: str           # 'articolo' | 'section' | 'allegato'
    section_number: str
    section_title: str
    section_path: str           # 'TITOLO I > Articolo 3. Definizioni'
    text: str                   # what we embed and what the LLM sees
    n_tokens: int
    n_chars: int
    page_start: int
    page_end: int
    chunk_index: int            # 0-based, ordering within the section
    n_chunks_in_section: int

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Path building ----------
def _full_section_path(s: Section, by_number: dict[str, Section]) -> str:
    """Walk the parent chain and build 'GP > Parent > Self' display string.

    Parents stored on a Section come in two forms:
      - another section's number/title we can look up (numbered docs)
      - a container header like 'CAPO 1' / 'TITOLO I' that has no Section row
    Both are handled — the latter is inserted as a literal and stops the walk.
    """
    parts: list[str] = []
    current: Section | None = s
    seen: set[str] = set()
    for _ in range(20):  # depth safety
        if current is None:
            break
        label = f"{current.number}. {current.title}".strip()
        parts.insert(0, label)
        seen.add(current.number)
        if not current.parent:
            break
        parent_key = current.parent.split(" ", 1)[0]
        if parent_key in seen:
            break
        parent = by_number.get(parent_key)
        if parent is None:
            # Container (CAPO/TITOLO/ALLEGATO) — keep literal and stop.
            parts.insert(0, current.parent)
            break
        current = parent
    return " > ".join(parts)


# ---------- Text splitting ----------
_PARA_SPLIT_RE = re.compile(r"\n\s*\n")
# Sentence boundary: period/!/? followed by whitespace and an uppercase letter
# (Italian/Latin range). The lookbehind keeps the terminator on the prior sentence.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý«])")


def _pack(units: list[str], joiner: str, target: int, hard_max: int) -> list[str]:
    """Greedily pack units into groups whose joined token count stays under target.

    The trailing group gets merged back into its predecessor if it's a tiny
    orphan (< MIN_TAIL_TOKENS) and the merge stays under hard_max.
    """
    out: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for u in units:
        ut = count_tokens(u)
        if ut > hard_max:
            # Caller's responsibility — we don't split here.
            if current:
                out.append(joiner.join(current))
                current, current_tokens = [], 0
            out.append(u)
            continue
        if current and current_tokens + ut > target:
            out.append(joiner.join(current))
            current = [u]
            current_tokens = ut
        else:
            current.append(u)
            current_tokens += ut
    if current:
        tail = joiner.join(current)
        if out and current_tokens < MIN_TAIL_TOKENS:
            merged = out[-1] + joiner + tail
            if count_tokens(merged) <= hard_max:
                out[-1] = merged
            else:
                out.append(tail)
        else:
            out.append(tail)
    return out


def split_body(text: str, target: int = TARGET_TOKENS, hard_max: int = MAX_TOKENS) -> list[str]:
    """Split a section body into chunks under hard_max tokens, targeting `target`.

    Strategy: paragraphs → sentences → hard truncate. We always prefer
    natural boundaries when they keep us under the cap.
    """
    paragraphs = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    if not paragraphs:
        return []

    # First pass: pack paragraphs.
    packed = _pack(paragraphs, "\n\n", target, hard_max)

    # Second pass: anything still over the cap gets re-split on sentences.
    final: list[str] = []
    for piece in packed:
        if count_tokens(piece) <= hard_max:
            final.append(piece)
            continue
        sentences = _SENT_SPLIT_RE.split(piece)
        sub_packed = _pack(sentences, " ", target, hard_max)

        # Third pass: any sentence still oversize gets hard-truncated by tokens.
        for sub in sub_packed:
            tok_count = count_tokens(sub)
            if tok_count <= hard_max:
                final.append(sub)
                continue
            ids = _enc().encode(sub)
            for start in range(0, len(ids), hard_max):
                final.append(_enc().decode(ids[start:start + hard_max]))
    return final


# ---------- Chunk id ----------
def _chunk_id(doc_id: str, section: Section, idx: int) -> str:
    """Deterministic id: same input → same chunk_id → idempotent upserts.

    Qdrant accepts uuid or unsigned int as point id. We use uuid-shaped ids
    derived from a stable string so the indexer can re-run safely.
    """
    raw = f"{doc_id}|{section.kind}|{section.number}|{idx}"
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()
    # Reformat as a UUID-shaped string (8-4-4-4-12)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ---------- Main entry point ----------
def chunk_document(
    doc_id: str,
    doc_type: str,
    cleaned: CleanedDoc,
    sections: list[Section],
    target_tokens: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[Chunk]:
    """Turn parsed sections into chunks. Each chunk's `text` is prefixed with
    the full section path so embeddings get hierarchical context for free."""
    by_number = {s.number: s for s in sections}
    chunks: list[Chunk] = []

    for s in sections:
        # Skip heading-only parents (their context lives in children's path).
        if s.n_chars < PARENT_ONLY_CHAR_THRESHOLD:
            continue

        body = cleaned.full_text[s.char_start:s.char_end].strip()
        path = _full_section_path(s, by_number)

        # Reserve room for the path prefix '[{path}]\n\n' that we prepend to
        # each chunk, so the final assembled text fits under max_tokens.
        prefix_tokens = count_tokens(f"[{path}]\n\n")
        body_budget = max(50, max_tokens - prefix_tokens)
        body_target = max(50, target_tokens - prefix_tokens)

        body_token_count = count_tokens(body)
        if body_token_count <= body_budget:
            pieces = [body]
        else:
            pieces = split_body(body, body_target, body_budget)

        for i, piece in enumerate(pieces):
            # Prepend section path for embedding-time context. Redundant with
            # the first chunk's natural heading, but makes every chunk
            # standalone — a search for 'definizioni' hits chunk 4 of art. 3.
            text = f"[{path}]\n\n{piece}"
            chunks.append(Chunk(
                chunk_id=_chunk_id(doc_id, s, i),
                doc_id=doc_id,
                doc_type=doc_type,
                section_kind=s.kind,
                section_number=s.number,
                section_title=s.title,
                section_path=path,
                text=text,
                n_tokens=count_tokens(text),
                n_chars=len(text),
                page_start=s.page_start,
                page_end=s.page_end,
                chunk_index=i,
                n_chunks_in_section=len(pieces),
            ))

    return chunks
