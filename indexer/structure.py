"""
Structure detection for Italian regulatory/technical PDFs.

Two recognized document types:
  - 'articolo': legal/regulatory text with 'Articolo N', optional 'CAPO N' /
    'TITOLO N' parents, and 'ALLEGATO X' annexes. Used by CELEX EU regulations
    and ARERA decisions (TIAD).
  - 'numbered': technical specs structured by numbered sections like '3.1.',
    '4.4.2.'. Used by Italian TSO technical attachments.

For each detected section we record the kind, number, title, parent container,
page range, character offsets, and a short text preview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from cleanup import CleanedDoc


# ---------- Anchors ----------
# Articolo N (optionally N bis/ter/quater/quinquies/sexies), at the start of a line.
ARTICLE_RE = re.compile(
    r"^\s*Articolo\s+(\d+)(?:\s*(bis|ter|quater|quinquies|sexies))?\b",
    re.MULTILINE | re.IGNORECASE,
)
# Container headers (treated as parents that "scope" the articles that follow).
CAPO_RE = re.compile(r"^\s*CAPO\s+([IVXLC0-9]+)\b", re.MULTILINE)
TITOLO_RE = re.compile(r"^\s*TITOLO\s+([IVXLC]+)\b", re.MULTILINE | re.IGNORECASE)
ALLEGATO_RE = re.compile(r"^\s*ALLEGATO\s+([IVXLC0-9]+)\b", re.MULTILINE | re.IGNORECASE)

# Numbered section like '3.', '3.1.', '4.4.2.' followed by a capitalized heading.
# We require the heading to start with a capital letter so we don't match bare
# enumerations like '1. ' inside an article body.
NUM_SECTION_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\.\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ][^\n]*)$",
    re.MULTILINE,
)

# A match looks like a TOC line if there's a dotted leader OR it ends with a
# trailing page number (e.g. '......... 12'). We only check the slice of text
# right after the heading match.
_TOC_TAIL_RE = re.compile(r"\.{3,}|\.\s*\d+\s*$")


@dataclass
class Section:
    kind: str                          # 'articolo' | 'section' | 'allegato'
    number: str                        # '12', '4bis', '3.1.2', 'I', 'II'
    title: str
    parent: Optional[str]              # 'CAPO II', 'TITOLO I', or None
    char_start: int
    char_end: int
    page_start: int
    page_end: int
    n_chars: int
    text_preview: str = field(default="")


# ---------- Doc-type detection ----------
def detect_doc_type(cleaned: CleanedDoc) -> str:
    """Pick 'articolo', 'numbered', or 'unknown' based on which anchors dominate.

    Articolo wins unconditionally when present — a legal doc with body
    paragraphs numbered '1.', '2.', '3.' inside articles will produce far
    more numbered-section matches than article matches, but it's still a
    legal doc and the numbered-section parser would mistake paragraphs
    for top-level sections.
    """
    text = cleaned.full_text
    n_articoli = len(ARTICLE_RE.findall(text))
    n_sections = len(NUM_SECTION_RE.findall(text))

    if n_articoli >= 5:
        return "articolo"
    if n_sections >= 5:
        return "numbered"
    return "unknown"


# ---------- Helpers ----------
# Look this far past the heading match when checking for TOC signals. We need
# enough room to catch dotted leaders on a second line (long TOC titles wrap).
_TOC_LOOKAHEAD = 500
# If the gap from this anchor to the next is smaller than this, the headings
# are clustered too tightly to be real article bodies — almost certainly TOC.
_TOC_MIN_BODY_GAP = 250


def _looks_like_toc_articolo(text_after: str, anchor_pos: int, next_anchor_pos: int) -> bool:
    """Heuristic: TOC entries have dotted leaders, trailing page numbers, or
    cluster tightly (anchors only a few hundred chars apart)."""
    if (next_anchor_pos - anchor_pos) < _TOC_MIN_BODY_GAP:
        return True
    sample = text_after[:_TOC_LOOKAHEAD].strip()
    if _TOC_TAIL_RE.search(sample):
        return True
    return False


def _looks_like_toc_numbered(title: str, text_after: str) -> bool:
    """Numbered-doc TOC entries also smuggle dotted leaders + page numbers
    INSIDE the matched title (the regex eats everything to end-of-line).

    No gap-based filter here: in technical docs, parent-only sections like
    '4. APPARECCHIATURE DI MISURA' have ~zero body chars before their first
    child '4.1', and that's normal — not TOC."""
    if "...." in title or _TOC_TAIL_RE.search(title):
        return True
    sample = text_after[:_TOC_LOOKAHEAD].strip()
    if _TOC_TAIL_RE.search(sample):
        return True
    return False


def _title_after(text: str, end_pos: int, max_chars: int = 200) -> str:
    """Pull the heading title that follows an anchor match."""
    tail = text[end_pos:end_pos + max_chars]
    # Skip leading whitespace/newlines
    tail = tail.lstrip("\n").lstrip()
    # First non-empty line is the title (legal docs put the title on its own line)
    line = tail.split("\n", 1)[0].strip()
    return line


def _preview(text: str, start: int, end: int, max_chars: int = 240) -> str:
    snippet = text[start:end].strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip() + "..."
    return snippet.replace("\n", " ")


# ---------- Parsers ----------
def parse_articolo_doc(cleaned: CleanedDoc) -> list[Section]:
    """Articolo-based parser for CELEX/TIAD-style documents.

    Walks the text linearly. Maintains the current 'parent' (most-recent
    CAPO/TITOLO/ALLEGATO). For each Articolo match, drops obvious TOC duplicates
    and emits a Section that runs until the next anchor.
    """
    text = cleaned.full_text

    # Collect every anchor with its kind + match info.
    anchors: list[tuple[int, str, re.Match]] = []
    for m in ARTICLE_RE.finditer(text):
        anchors.append((m.start(), "articolo", m))
    for m in CAPO_RE.finditer(text):
        anchors.append((m.start(), "capo", m))
    for m in TITOLO_RE.finditer(text):
        anchors.append((m.start(), "titolo", m))
    for m in ALLEGATO_RE.finditer(text):
        anchors.append((m.start(), "allegato", m))
    anchors.sort(key=lambda x: x[0])

    sections: list[Section] = []
    current_parent: Optional[str] = None

    for i, (pos, kind, m) in enumerate(anchors):
        next_pos = anchors[i + 1][0] if i + 1 < len(anchors) else len(text)

        # Update parent context for containers; they don't emit a Section on
        # their own (the Allegato is an exception — we emit those).
        if kind == "capo":
            current_parent = f"CAPO {m.group(1)}"
            continue
        if kind == "titolo":
            current_parent = f"TITOLO {m.group(1)}"
            continue
        if kind == "allegato":
            number = m.group(1)
            title = _title_after(text, m.end())
            sections.append(Section(
                kind="allegato",
                number=number,
                title=title,
                parent=None,
                char_start=pos,
                char_end=next_pos,
                page_start=cleaned.page_of(pos),
                page_end=cleaned.page_of(max(pos, next_pos - 1)),
                n_chars=next_pos - pos,
                text_preview=_preview(text, pos, next_pos),
            ))
            # An allegato resets the parent context (no CAPO inside annexes).
            current_parent = f"ALLEGATO {number}"
            continue

        # kind == 'articolo'
        if _looks_like_toc_articolo(text[m.end():], pos, next_pos):
            continue

        num = m.group(1)
        suffix = m.group(2) or ""
        number = f"{num}{suffix.lower()}" if suffix else num
        title = _title_after(text, m.end())

        sections.append(Section(
            kind="articolo",
            number=number,
            title=title,
            parent=current_parent,
            char_start=pos,
            char_end=next_pos,
            page_start=cleaned.page_of(pos),
            page_end=cleaned.page_of(max(pos, next_pos - 1)),
            n_chars=next_pos - pos,
            text_preview=_preview(text, pos, next_pos),
        ))

    return sections


def parse_numbered_doc(cleaned: CleanedDoc) -> list[Section]:
    """Numbered-section parser for technical-spec PDFs (e.g., Allegato A.43).

    Sections nest by dotted number: '4' is the parent of '4.4', which is the
    parent of '4.4.2'. We attach `parent` to the nearest shallower ancestor.
    """
    text = cleaned.full_text

    matches = list(NUM_SECTION_RE.finditer(text))
    # Drop TOC-like matches and paragraph-number false-positives.
    #
    # The body of an article in 59.pdf-style docs contains numbered enumerations
    # like '1. Verifica...', '2. Confronto...' on their own lines. Those match
    # our regex too. We guard against them by tracking the highest top-level
    # section number seen so far: a real top-level section number can't go
    # *backward*, but a body enumeration restarts at 1.
    body_matches: list[re.Match] = []
    highest_top_level = 0
    for m in matches:
        number = m.group(1)
        title = m.group(2)

        if _looks_like_toc_numbered(title, text[m.end():]):
            continue

        top_level = int(number.split(".", 1)[0])
        if top_level < highest_top_level:
            # We're past section N already; this '2.' / '3.' must be a
            # paragraph inside an article body, not a new top section.
            continue
        if top_level > highest_top_level:
            highest_top_level = top_level

        body_matches.append(m)

    sections: list[Section] = []
    parent_stack: list[tuple[int, str]] = []  # (depth, "number Title")

    for i, m in enumerate(body_matches):
        pos = m.start()
        next_pos = body_matches[i + 1].start() if i + 1 < len(body_matches) else len(text)

        number = m.group(1)
        title = m.group(2).strip()
        depth = number.count(".") + 1

        # Pop any stack entries that aren't ancestors of this section.
        while parent_stack and parent_stack[-1][0] >= depth:
            parent_stack.pop()
        parent = parent_stack[-1][1] if parent_stack else None
        parent_stack.append((depth, f"{number} {title}"))

        sections.append(Section(
            kind="section",
            number=number,
            title=title,
            parent=parent,
            char_start=pos,
            char_end=next_pos,
            page_start=cleaned.page_of(pos),
            page_end=cleaned.page_of(max(pos, next_pos - 1)),
            n_chars=next_pos - pos,
            text_preview=_preview(text, pos, next_pos),
        ))

    return sections


def parse(cleaned: CleanedDoc) -> tuple[str, list[Section]]:
    """Detect the doc type and return (doc_type, sections)."""
    doc_type = detect_doc_type(cleaned)
    if doc_type == "articolo":
        return doc_type, parse_articolo_doc(cleaned)
    if doc_type == "numbered":
        return doc_type, parse_numbered_doc(cleaned)
    return doc_type, []
