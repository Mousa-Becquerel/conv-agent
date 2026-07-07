"""
Step 3 of the indexing pipeline: turn parsed sections into Chunks and dump
both a human-readable summary and a JSONL of all chunks per document.

The summary lands in out/analyze_chunks_<docname>.txt — we eyeball this to
confirm token sizes, section coverage, and that path-prefixed text looks sane.
The JSONL in out/chunks_<docname>.jsonl is what the next step (embed + upsert
to Qdrant) will consume.

Run inside the indexer container:
    docker compose run --rm indexer python analyze_chunks.py
"""

import json
import os
from collections import Counter
from pathlib import Path

import pdfplumber

from cleanup import clean_pages
from chunker import Chunk, chunk_document
from structure import parse


SAMPLE_DIR = Path(os.getenv("SAMPLE_DIR", "/data/sample"))
OUT_DIR = Path(os.getenv("OUT_DIR", "/app/out"))


def extract_pages(path: Path) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def _doc_id_from_path(path: Path) -> str:
    """Stable slug we can use as Qdrant payload + part of chunk_id."""
    return path.stem.lower().replace(" ", "_")


def _token_buckets(chunks: list[Chunk]) -> Counter[str]:
    buckets: Counter[str] = Counter()
    for c in chunks:
        if c.n_tokens < 100:
            buckets["<100"] += 1
        elif c.n_tokens < 300:
            buckets["100-300"] += 1
        elif c.n_tokens < 500:
            buckets["300-500"] += 1
        elif c.n_tokens < 700:
            buckets["500-700"] += 1
        elif c.n_tokens <= 800:
            buckets["700-800"] += 1
        else:
            buckets[">800"] += 1
    return buckets


def analyze_pdf(path: Path, out_dir: Path) -> None:
    doc_id = _doc_id_from_path(path)
    txt_path = out_dir / f"analyze_chunks_{path.stem}.txt"
    jsonl_path = out_dir / f"chunks_{path.stem}.jsonl"
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    raw_pages = extract_pages(path)
    cleaned = clean_pages(raw_pages)
    doc_type, sections = parse(cleaned)
    chunks = chunk_document(doc_id, doc_type, cleaned, sections)

    w(f"=== {path.name} ===")
    w(f"doc_id: {doc_id}")
    w(f"doc_type: {doc_type}")
    w(f"sections: {len(sections)}  (parents-only dropped at chunk time)")
    w(f"chunks: {len(chunks)}")
    if chunks:
        token_total = sum(c.n_tokens for c in chunks)
        token_avg = token_total / len(chunks)
        token_max = max(c.n_tokens for c in chunks)
        w(f"tokens: total={token_total:,}  avg={token_avg:.0f}  max={token_max}")
    w("")

    w("--- token size distribution ---")
    buckets = _token_buckets(chunks)
    for k in ("<100", "100-300", "300-500", "500-700", "700-800", ">800"):
        if buckets[k]:
            w(f"  {k}: {buckets[k]}")
    w("")

    # Sections producing many chunks — the ones the chunker had to subdivide.
    chunks_per_section: Counter[tuple[str, str]] = Counter()
    for c in chunks:
        chunks_per_section[(c.section_kind, c.section_number)] += 1
    multi = sorted(
        [(k, v) for k, v in chunks_per_section.items() if v > 1],
        key=lambda x: -x[1],
    )
    w(f"--- sections that subdivided into >1 chunk ({len(multi)}) ---")
    for (kind, num), count in multi[:15]:
        # Find the section title from a chunk
        title = next(
            (c.section_title for c in chunks if c.section_kind == kind and c.section_number == num),
            "",
        )
        w(f"  {kind} {num}: {count} chunks — {title}")
    w("")

    # Sample chunks: first chunk (a small standalone), one mid-doc chunk,
    # and one sub-chunk from the biggest section.
    if chunks:
        w("--- sample chunks ---")
        sample_indices = sorted({0, len(chunks) // 2, len(chunks) - 1})
        # Also include a sub-chunk (chunk_index >= 1) if any exists.
        sub = next((i for i, c in enumerate(chunks) if c.chunk_index >= 1), None)
        if sub is not None and sub not in sample_indices:
            sample_indices = sorted(sample_indices + [sub])

        for i in sample_indices:
            c = chunks[i]
            w(f"  [chunk {i}/{len(chunks) - 1}] chunk_id={c.chunk_id}")
            w(f"    path: {c.section_path}")
            w(f"    chunk_index: {c.chunk_index} of {c.n_chunks_in_section}")
            w(f"    pages: {c.page_start}-{c.page_end}  tokens: {c.n_tokens}  chars: {c.n_chars}")
            preview = c.text[:600].replace("\n", " ")
            if len(c.text) > 600:
                preview += "..."
            w(f"    text: {preview}")
            w("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    with jsonl_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    print(f"wrote {txt_path}  ({len(chunks)} chunks)")
    print(f"wrote {jsonl_path}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(SAMPLE_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs found in {SAMPLE_DIR}")
        return

    print(f"chunking {len(pdfs)} PDFs from {SAMPLE_DIR}")
    for pdf_path in pdfs:
        try:
            analyze_pdf(pdf_path, OUT_DIR)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"ERROR on {pdf_path.name}: {e}")


if __name__ == "__main__":
    main()
