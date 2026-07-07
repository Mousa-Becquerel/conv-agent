"""
Inspect sample PDFs with pdfplumber.

Step 0 of the indexing pipeline: see what extraction quality we get
before committing to a chunker. For each PDF in SAMPLE_DIR:
  - print PDF metadata + page count
  - extract every page, accumulate char-count stats
  - flag empty / low-text pages (likely scanned)
  - count structure markers we plan to chunk on (Articolo, TITOLO, CAPO, ALLEGATO)
  - dump a sample of pages to out/inspect_<docname>.txt for human review

Run inside the indexer container:
    docker compose run --rm indexer python inspect_pdf.py
"""

import os
import re
from pathlib import Path

import pdfplumber


SAMPLE_DIR = Path(os.getenv("SAMPLE_DIR", "/data/sample"))
OUT_DIR = Path(os.getenv("OUT_DIR", "/app/out"))

# Italian regulatory/technical structure anchors.
# Anchored to start-of-line (MULTILINE) so we don't match these words mid-sentence.
ARTICLE_RE = re.compile(r"^\s*Articolo\s+(\d+)", re.MULTILINE | re.IGNORECASE)
TITOLO_RE = re.compile(r"^\s*TITOLO\s+[IVXLC]+", re.MULTILINE)
CAPO_RE = re.compile(r"^\s*CAPO\s+[IVXLC0-9]+", re.MULTILINE)
ALLEGATO_RE = re.compile(r"^\s*ALLEGATO\s+[IVXLC0-9]+", re.MULTILINE)

# Pages below this many chars are probably scanned / image-heavy and
# will need OCR before they're useful.
LOW_TEXT_THRESHOLD = 100

# How much of each sampled page to dump into the output file.
PAGE_PREVIEW_CHARS = 2000


def _fmt_list(items, limit=20):
    """Render a list with a '...' tail if it's longer than `limit`."""
    head = items[:limit]
    tail = "..." if len(items) > limit else ""
    return f"{head}{tail}"


def inspect_pdf(path: Path, out_dir: Path) -> None:
    out_path = out_dir / f"inspect_{path.stem}.txt"
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    with pdfplumber.open(path) as pdf:
        n_pages = len(pdf.pages)
        meta = pdf.metadata or {}

        w(f"=== {path.name} ===")
        w(f"file size: {path.stat().st_size:,} bytes")
        w(f"pages: {n_pages}")
        w("metadata:")
        for k, v in meta.items():
            w(f"  {k}: {v}")
        w("")

        # Pass 1: extract text from every page, accumulate stats.
        page_texts: list[str] = []
        for page in pdf.pages:
            page_texts.append(page.extract_text() or "")

    char_counts = [len(t) for t in page_texts]
    total_chars = sum(char_counts)
    empty_pages = [i + 1 for i, c in enumerate(char_counts) if c == 0]
    low_text_pages = [
        i + 1 for i, c in enumerate(char_counts)
        if 0 < c < LOW_TEXT_THRESHOLD
    ]
    avg_chars = total_chars / n_pages if n_pages else 0

    w("--- text extraction stats ---")
    w(f"total chars: {total_chars:,}")
    w(f"avg chars/page: {avg_chars:.0f}")
    w(f"empty pages ({len(empty_pages)}): {_fmt_list(empty_pages)}")
    w(
        f"low-text pages (<{LOW_TEXT_THRESHOLD} chars, {len(low_text_pages)}): "
        f"{_fmt_list(low_text_pages)}"
    )
    w("")

    # Structure markers across the entire document (after joining pages).
    full_text = "\n".join(page_texts)
    articoli = ARTICLE_RE.findall(full_text)
    titoli = TITOLO_RE.findall(full_text)
    capi = CAPO_RE.findall(full_text)
    allegati = ALLEGATO_RE.findall(full_text)

    w("--- structure markers (whole doc) ---")
    w(f"Articolo N matches: {len(articoli)} (numbers: {_fmt_list(articoli)})")
    w(f"TITOLO matches: {len(titoli)}")
    w(f"CAPO matches: {len(capi)}")
    w(f"ALLEGATO matches: {len(allegati)}")
    w("")

    # Sample pages: 1, 2, midpoint, last (deduped, clamped to range).
    sample_indices = sorted(
        {0, 1, n_pages // 2, n_pages - 1} & set(range(n_pages))
    )
    for idx in sample_indices:
        text = page_texts[idx]
        w(f"--- page {idx + 1} ({char_counts[idx]} chars) ---")
        w(text[:PAGE_PREVIEW_CHARS])
        if len(text) > PAGE_PREVIEW_CHARS:
            w("... [truncated]")
        w("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path} ({len(lines)} lines)")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(SAMPLE_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs found in {SAMPLE_DIR}")
        return

    print(f"inspecting {len(pdfs)} PDFs from {SAMPLE_DIR}")
    for pdf_path in pdfs:
        try:
            inspect_pdf(pdf_path, OUT_DIR)
        except Exception as e:
            print(f"ERROR on {pdf_path.name}: {e}")


if __name__ == "__main__":
    main()
