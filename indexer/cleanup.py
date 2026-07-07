"""
Page-level cleanup: strip running headers/footers, fix line-break hyphenation,
normalize whitespace, and assemble pages into a single text with an offset→page map.

Header/footer detection is frequency-based: lines that appear at the top or
bottom of >=30% of pages (digits normalized so 'Pag. 5 di 19' clusters with
'Pag. 6 di 19') are treated as running material and stripped from edges only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


# Number of lines at the top/bottom of each page that are candidates for
# being a running header/footer. Anything beyond this is treated as body.
# We use a generous top window because 59.pdf-style technical docs put a
# 7-line banner at the top of every page (org + doc id + revision + page
# number + date).
EDGE_TOP = 8
EDGE_BOTTOM = 3

# A normalized line counts as a running header/footer if it shows up on
# at least this fraction of pages, with a minimum of MIN_OCCURRENCES.
FREQUENCY_THRESHOLD = 0.3
MIN_OCCURRENCES = 3

_DIGITS_RE = re.compile(r"\d+")
_SOFT_HYPHEN_BREAK_RE = re.compile(r"­\n\s*")
_HARD_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n\s*([a-zà-ÿ])")
_MULTI_BLANKLINE_RE = re.compile(r"\n{3,}")

# Lines that look like structural anchors must NEVER be stripped as running
# headers, even if frequency-based detection flags them. In CELEX, lots of
# articles begin at the top of a page, so 'Articolo N' lines cluster on edges
# — but they are real content, not headers.
_STRUCTURAL_ANCHOR_RE = re.compile(
    r"^\s*(Articolo\s+\d+|CAPO\s+[IVXLC0-9]+|TITOLO\s+[IVXLC]+|ALLEGATO\s+[IVXLC0-9]+)\b",
    re.IGNORECASE,
)


def _normalize_for_freq(line: str) -> str:
    """Collapse digit runs to '#' so page-numbered footers cluster together."""
    return _DIGITS_RE.sub("#", line.strip())


def detect_running_lines(pages: list[str]) -> set[str]:
    """Return the set of normalized lines that appear as headers/footers on enough pages."""
    counter: Counter[str] = Counter()
    for page in pages:
        lines = [ln for ln in page.split("\n") if ln.strip()]
        edges = lines[:EDGE_TOP] + lines[-EDGE_BOTTOM:] if lines else []
        for ln in edges:
            counter[_normalize_for_freq(ln)] += 1

    threshold = max(MIN_OCCURRENCES, int(len(pages) * FREQUENCY_THRESHOLD))
    return {norm for norm, c in counter.items() if c >= threshold}


def _is_strippable(line: str, running: set[str]) -> bool:
    """A line is strippable if it's in the frequency-based running set AND
    doesn't look like a structural anchor (which is real content)."""
    if _STRUCTURAL_ANCHOR_RE.match(line):
        return False
    return _normalize_for_freq(line) in running


def strip_running_from_page(page_text: str, running: set[str]) -> str:
    """Strip running lines, but only when they appear at the top/bottom edges of the page."""
    lines = page_text.split("\n")

    # Top: consume blank lines + up to EDGE_TOP running-line matches, in any order.
    top_cut = 0
    seen_running_top = 0
    for i, ln in enumerate(lines[:EDGE_TOP + 5]):
        if not ln.strip():
            top_cut = i + 1
            continue
        if _is_strippable(ln, running):
            top_cut = i + 1
            seen_running_top += 1
            if seen_running_top >= EDGE_TOP:
                break
            continue
        break

    # Bottom: same logic in reverse.
    bottom_cut = len(lines)
    seen_running_bot = 0
    for i in range(len(lines) - 1, max(-1, len(lines) - EDGE_BOTTOM - 5), -1):
        ln = lines[i]
        if not ln.strip():
            bottom_cut = i
            continue
        if _is_strippable(ln, running):
            bottom_cut = i
            seen_running_bot += 1
            if seen_running_bot >= EDGE_BOTTOM:
                break
            continue
        break

    return "\n".join(lines[top_cut:bottom_cut])


def dehyphenate(text: str) -> str:
    """Glue words split across line breaks by either soft or hard hyphens."""
    text = _SOFT_HYPHEN_BREAK_RE.sub("", text)
    text = _HARD_HYPHEN_BREAK_RE.sub(r"\1\2", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse 3+ blank lines to 2, strip trailing spaces per line."""
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    text = _MULTI_BLANKLINE_RE.sub("\n\n", text)
    return text.strip()


@dataclass
class CleanedDoc:
    pages: list[str]          # cleaned per-page text
    full_text: str            # all pages joined with '\n\n'
    page_starts: list[int]    # char offset where each page starts in full_text
    running_lines: set[str]   # normalized running headers/footers we stripped

    def page_of(self, offset: int) -> int:
        """1-based page number for a character offset in full_text."""
        # Linear scan is fine here; we call this only a handful of times per doc.
        page = 1
        for i, start in enumerate(self.page_starts):
            if offset >= start:
                page = i + 1
            else:
                break
        return page


def _strip_running_global(page_text: str, running: set[str]) -> str:
    """Strip running lines wherever they appear on a page, not only at edges.

    Needed for pages where pdfplumber returns text in non-reading order
    (e.g. diagram pages in 59.pdf), so banner lines end up scattered through
    the extracted text instead of clustering at the top. Safe because
    `_is_strippable` already excludes structural anchors like 'Articolo N'.
    """
    lines = page_text.split("\n")
    return "\n".join(ln for ln in lines if not _is_strippable(ln, running))


def clean_pages(raw_pages: list[str]) -> CleanedDoc:
    """Run the full cleanup pipeline on a list of per-page texts."""
    running = detect_running_lines(raw_pages)
    cleaned_pages = []
    for page in raw_pages:
        page = strip_running_from_page(page, running)
        page = _strip_running_global(page, running)
        page = dehyphenate(page)
        page = normalize_whitespace(page)
        cleaned_pages.append(page)

    # Assemble with explicit page boundaries we can map back from offsets.
    SEPARATOR = "\n\n"
    parts: list[str] = []
    starts: list[int] = []
    offset = 0
    for i, page in enumerate(cleaned_pages):
        starts.append(offset)
        parts.append(page)
        offset += len(page) + (len(SEPARATOR) if i < len(cleaned_pages) - 1 else 0)

    return CleanedDoc(
        pages=cleaned_pages,
        full_text=SEPARATOR.join(parts),
        page_starts=starts,
        running_lines=running,
    )
