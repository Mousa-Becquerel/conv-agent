"""
Smoke test for the indexed Qdrant collection.

Embeds a short list of Italian probe queries and prints top-k results so we
can eyeball whether retrieval surfaces the right articles before wiring up
an LLM. No LangChain, no reranker — pure dense vector search to validate
the indexer end-to-end.

Run inside the indexer container (qdrant must be up):
    docker compose run --rm indexer python smoke_query.py
"""

import os
import sys

from openai import OpenAI
from qdrant_client import QdrantClient


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "conv_agent_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

TOP_K = 5

# Probe queries — each tagged with the doc we expect to dominate the results,
# so we can scan the output and spot obvious misses.
PROBES = [
    ("Cosa si intende per autoconsumo diffuso?", "727-22tiad"),
    ("Quali sono gli adempimenti del GSE per il referente?", "727-22tiad"),
    ("Quali sono gli obblighi dei TSO in materia di controllo della tensione?", "celex"),
    ("Come si classificano gli stati del sistema elettrico?", "celex"),
    ("Quali protocolli di comunicazione usa il SAPR?", "59"),
    ("Che cos'è un'apparecchiatura di misura?", "59"),
]


def main() -> None:
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    client_oa = OpenAI(api_key=OPENAI_API_KEY)
    client_qd = QdrantClient(url=QDRANT_URL, timeout=30)

    if not client_qd.collection_exists(COLLECTION_NAME):
        print(f"ERROR: collection '{COLLECTION_NAME}' does not exist — run index.py first")
        sys.exit(1)

    info = client_qd.get_collection(COLLECTION_NAME)
    print(f"collection '{COLLECTION_NAME}': {info.points_count} points")
    print(f"model: {EMBEDDING_MODEL}")
    print()

    for query, expected_doc in PROBES:
        # Embed the query
        resp = client_oa.embeddings.create(model=EMBEDDING_MODEL, input=[query])
        vec = resp.data[0].embedding

        hits = client_qd.search(
            collection_name=COLLECTION_NAME,
            query_vector=vec,
            limit=TOP_K,
            with_payload=True,
        )

        print(f"❓ {query}")
        print(f"   (expecting hits from {expected_doc!r})")
        for rank, h in enumerate(hits, 1):
            meta = h.payload.get("metadata", {})
            doc_id = meta.get("doc_id", "?")
            kind = meta.get("section_kind", "?")
            num = meta.get("section_number", "?")
            title = meta.get("section_title", "")
            path = meta.get("section_path", "")
            pages = f"p.{meta.get('page_start', '?')}-{meta.get('page_end', '?')}"
            marker = "✓" if expected_doc in doc_id else " "
            print(
                f"   {marker} #{rank}  score={h.score:.3f}  {doc_id}  "
                f"{kind} {num}  {pages}"
            )
            print(f"        {path}")
        print()


if __name__ == "__main__":
    main()
