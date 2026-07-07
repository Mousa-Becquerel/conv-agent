"""
Step 2 of the indexing pipeline: read each sample PDF, run cleanup, detect doc
type, parse sections, and dump a human-readable analysis to out/.

The output is the artifact we eyeball before writing the chunker. We want to
confirm:
  - the right doc_type was assigned to each PDF
  - running headers/footers were detected and stripped
  - section/article boundaries match what we expect
  - no section is absurdly large (a hint that we'll need sub-chunking later)

Run inside the indexer container:
    docker compose run --rm indexer python analyze_structure.py
"""

import os
from collections import Counter
from pathlib import Path

import pdfplumber

from cleanup import clean_pages
from structure import Section, parse


SAMPLE_DIR = Path(os.getenv("SAMPLE_DIR", "/data/sample"))
OUT_DIR = Path(os.getenv("OUT_DIR", "/app/out"))


def extract_pages(path: Path) -> list[str]:
    """Pull raw per-page text via pdfplumber."""
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def _format_section_line(s: Section) -> str:
    parent = f"[{s.parent}] " if s.parent else ""
    label = {
        "articolo": "Articolo",
        "section": "Section",
        "allegato": "ALLEGATO",
    }.get(s.kind, s.kind)
    pages = f"p.{s.page_start}" if s.page_start == s.page_end else f"p.{s.page_start}-{s.page_end}"
    return f"  {parent}{label} {s.number}: {s.title}  ({pages}, {s.n_chars} chars)"


def _section_size_buckets(sections: list[Section]) -> Counter[str]:
    """Bucket section sizes so we see at a glance how chunky the doc is."""
    buckets: Counter[str] = Counter()
    for s in sections:
        if s.n_chars < 500:
            buckets["<500"] += 1
        elif s.n_chars < 2000:
            buckets["500-2k"] += 1
        elif s.n_chars < 5000:
            buckets["2k-5k"] += 1
        elif s.n_chars < 10000:
            buckets["5k-10k"] += 1
        else:
            buckets["10k+"] += 1
    return buckets


def analyze_pdf(path: Path, out_dir: Path) -> None:
    out_path = out_dir / f"analyze_{path.stem}.txt"
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    raw_pages = extract_pages(path)
    cleaned = clean_pages(raw_pages)
    doc_type, sections = parse(cleaned)

    raw_chars = sum(len(p) for p in raw_pages)
    cleaned_chars = len(cleaned.full_text)

    w(f"=== {path.name} ===")
    w(f"pages: {len(raw_pages)}")
    w(f"raw chars: {raw_chars:,}")
    w(f"cleaned chars: {cleaned_chars:,}  (stripped {raw_chars - cleaned_chars:,})")
    w(f"doc_type: {doc_type}")
    w("")

    w(f"--- running lines stripped from edges ({len(cleaned.running_lines)}) ---")
    for ln in sorted(cleaned.running_lines):
        w(f"  '{ln}'")
    w("")

    w(f"--- sections found: {len(sections)} ---")
    buckets = _section_size_buckets(sections)
    bucket_summary = ", ".join(f"{k}: {buckets[k]}" for k in ("<500", "500-2k", "2k-5k", "5k-10k", "10k+") if buckets[k])
    w(f"size distribution: {bucket_summary if bucket_summary else '(none)'}")
    w("")

    # Print every section, but cap at 30 to keep the file scannable for long docs.
    SHOW_LIMIT = 30
    for s in sections[:SHOW_LIMIT]:
        w(_format_section_line(s))
    if len(sections) > SHOW_LIMIT:
        w(f"  ... ({len(sections) - SHOW_LIMIT} more)")
    w("")

    # Show one full section as a sample of what the chunker would see.
    # Prefer something in the middle to skip preambles/TOC.
    if sections:
        sample_idx = len(sections) // 2
        s = sections[sample_idx]
        w(f"--- sample full section: {s.kind} {s.number} (idx {sample_idx}) ---")
        body = cleaned.full_text[s.char_start:s.char_end].strip()
        w(body[:3000])
        if len(body) > 3000:
            w(f"... [truncated, total {len(body)} chars]")
        w("")

    # Largest section — if this is 10k+ chars we'll definitely need sub-chunking.
    if sections:
        biggest = max(sections, key=lambda x: x.n_chars)
        w(f"--- largest section: {biggest.kind} {biggest.number} "
          f"({biggest.n_chars:,} chars, p.{biggest.page_start}-{biggest.page_end}) ---")
        w(f"  title: {biggest.title}")
        w(f"  parent: {biggest.parent}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}  (doc_type={doc_type}, sections={len(sections)})")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(SAMPLE_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs found in {SAMPLE_DIR}")
        return

    print(f"analyzing {len(pdfs)} PDFs from {SAMPLE_DIR}")
    for pdf_path in pdfs:
        try:
            analyze_pdf(pdf_path, OUT_DIR)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"ERROR on {pdf_path.name}: {e}")


if __name__ == "__main__":
    main()
