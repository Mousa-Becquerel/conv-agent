"""
Step 4: embed chunks and upsert them into Qdrant.

Reads every out/chunks_*.jsonl produced by analyze_chunks.py, embeds each
chunk's text with text-embedding-3-large, and upserts to Qdrant under the
configured collection. chunk_ids are deterministic, so re-runs replace
existing points rather than duplicating them.

Payload layout mirrors LangChain's QdrantVectorStore convention (top-level
`page_content` + `metadata`) so we can plug a langchain-qdrant retriever
into the API later without re-indexing.

Run inside the indexer container (with qdrant already up):
    docker compose up -d qdrant
    docker compose run --rm indexer python index.py

Env knobs:
    OPENAI_API_KEY      (required)
    QDRANT_URL          (default: http://qdrant:6333)
    COLLECTION_NAME     (default: conv_agent_chunks)
    EMBEDDING_MODEL     (default: text-embedding-3-large)
    RESET_COLLECTION    set to 'true' to drop and recreate the collection
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from tqdm import tqdm


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "conv_agent_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
OUT_DIR = Path(os.getenv("OUT_DIR", "/app/out"))
RESET_COLLECTION = os.getenv("RESET_COLLECTION", "false").lower() == "true"

VECTOR_SIZE = 3072  # text-embedding-3-large
BATCH_SIZE = 64

# Payload fields we want indexed for fast filtering at query time.
# Stored under `metadata.*` to match the LangChain QdrantVectorStore layout.
PAYLOAD_INDEXES: list[tuple[str, qmodels.PayloadSchemaType]] = [
    ("metadata.doc_id", qmodels.PayloadSchemaType.KEYWORD),
    ("metadata.doc_type", qmodels.PayloadSchemaType.KEYWORD),
    ("metadata.section_kind", qmodels.PayloadSchemaType.KEYWORD),
    ("metadata.section_number", qmodels.PayloadSchemaType.KEYWORD),
    ("metadata.page_start", qmodels.PayloadSchemaType.INTEGER),
]


def _load_chunks(jsonl_path: Path):
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def _ensure_collection(client: QdrantClient) -> None:
    exists = client.collection_exists(COLLECTION_NAME)

    if exists and RESET_COLLECTION:
        print(f"RESET_COLLECTION=true → deleting '{COLLECTION_NAME}'")
        client.delete_collection(COLLECTION_NAME)
        exists = False

    if exists:
        print(f"collection '{COLLECTION_NAME}' already exists — upserting in place")
        return

    print(f"creating collection '{COLLECTION_NAME}' (size={VECTOR_SIZE}, cosine)")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qmodels.VectorParams(
            size=VECTOR_SIZE,
            distance=qmodels.Distance.COSINE,
        ),
    )
    for field, schema in PAYLOAD_INDEXES:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=schema,
        )
    print(f"created payload indexes on: {', '.join(f for f, _ in PAYLOAD_INDEXES)}")


def _embed_batch(client_oa: OpenAI, texts: list[str]) -> list[list[float]]:
    resp = client_oa.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def _to_point(chunk: dict, vector: list[float]) -> qmodels.PointStruct:
    """Wrap chunk in the {page_content, metadata} payload LangChain expects."""
    payload = {
        "page_content": chunk["text"],
        "metadata": {k: v for k, v in chunk.items() if k != "text"},
    }
    return qmodels.PointStruct(
        id=chunk["chunk_id"],
        vector=vector,
        payload=payload,
    )


def _index_jsonl(client_qd: QdrantClient, client_oa: OpenAI, path: Path) -> int:
    chunks = list(_load_chunks(path))
    n = len(chunks)
    if not n:
        print(f"  {path.name}: empty, skipping")
        return 0

    with tqdm(total=n, desc=path.stem, unit="chunks") as pbar:
        for i in range(0, n, BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            texts = [c["text"] for c in batch]
            vectors = _embed_batch(client_oa, texts)
            points = [_to_point(c, v) for c, v in zip(batch, vectors)]
            client_qd.upsert(
                collection_name=COLLECTION_NAME,
                wait=True,
                points=points,
            )
            pbar.update(len(batch))

    return n


def main() -> None:
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    jsonls = sorted(OUT_DIR.glob("chunks_*.jsonl"))
    if not jsonls:
        print(f"ERROR: no chunks_*.jsonl files in {OUT_DIR} — run analyze_chunks.py first")
        sys.exit(1)

    print(f"📚 indexing {len(jsonls)} document(s) into '{COLLECTION_NAME}' at {QDRANT_URL}")

    client_oa = OpenAI(api_key=OPENAI_API_KEY)
    client_qd = QdrantClient(url=QDRANT_URL, timeout=60)
    _ensure_collection(client_qd)

    total = 0
    for path in jsonls:
        total += _index_jsonl(client_qd, client_oa, path)

    info = client_qd.get_collection(COLLECTION_NAME)
    print(f"\n✅ upserted {total} chunks across {len(jsonls)} document(s)")
    print(f"   collection points_count: {info.points_count}")


if __name__ == "__main__":
    main()
