"""Vector store wrapper around a persistent local ChromaDB.

Persists to `chroma/` inside the data volume. We compute embeddings ourselves
(via `app.rag.embeddings`) and pass them in explicitly, so Chroma never reaches
out to any embedding API — everything stays local and offline.

Indexing is idempotent per document: a document is keyed by its content hash, and
re-indexing the same content is a no-op. Chunk ids are derived from that hash so
re-adding replaces rather than duplicates.
"""

from __future__ import annotations

import threading

from app.config import Config
from app.rag.embeddings import embed_texts
from app.rag.splitter import split_text

_COLLECTION = "documents"

_client = None
_collection = None
_lock = threading.Lock()


class VectorStoreError(Exception):
    """Raised on vector-store initialization or operation failure."""


def _get_collection(cfg: Config):
    global _client, _collection
    if _collection is not None:
        return _collection
    with _lock:
        if _collection is not None:
            return _collection
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VectorStoreError("Vector store requires the 'chromadb' package.") from exc
        try:
            _client = chromadb.PersistentClient(
                path=str(cfg.chroma_dir),
                settings=Settings(anonymized_telemetry=False, allow_reset=False),
            )
            _collection = _client.get_or_create_collection(
                name=_COLLECTION, metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:
            raise VectorStoreError(f"Could not open vector store: {exc}") from exc
    return _collection


def document_exists(doc_hash: str, cfg: Config) -> bool:
    """Return True if a document with this content hash is already indexed."""
    col = _get_collection(cfg)
    try:
        existing = col.get(where={"doc_hash": doc_hash}, limit=1)
        return bool(existing and existing.get("ids"))
    except Exception:
        return False


def index_document(
    *, doc_hash: str, stored_name: str, text: str, cfg: Config
) -> dict:
    """Chunk, embed, and persist a document. Idempotent on ``doc_hash``.

    Returns a summary dict ``{stored_name, doc_hash, chunks, skipped}``.
    """
    col = _get_collection(cfg)

    if document_exists(doc_hash, cfg):
        return {"stored_name": stored_name, "doc_hash": doc_hash, "chunks": 0, "skipped": True}

    chunks = split_text(text, cfg)
    if not chunks:
        return {"stored_name": stored_name, "doc_hash": doc_hash, "chunks": 0, "skipped": True}

    documents = [c.text for c in chunks]
    embeddings = embed_texts(documents, cfg)
    ids = [f"{doc_hash}:{c.index}" for c in chunks]
    metadatas = [
        {"doc_hash": doc_hash, "stored_name": stored_name, "chunk_index": c.index}
        for c in chunks
    ]

    col.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    return {
        "stored_name": stored_name,
        "doc_hash": doc_hash,
        "chunks": len(chunks),
        "skipped": False,
    }


def query(embedding: list[float], top_k: int, cfg: Config) -> list[dict]:
    """Return the top-k most similar chunks for a query embedding."""
    col = _get_collection(cfg)
    res = col.query(
        query_embeddings=[embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    out: list[dict] = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        out.append(
            {
                "text": doc,
                "stored_name": (meta or {}).get("stored_name", "unknown"),
                "chunk_index": (meta or {}).get("chunk_index"),
                # cosine distance → similarity score in [0, 1]
                "score": round(1.0 - float(dist), 4),
            }
        )
    return out


def stats(cfg: Config) -> dict:
    """Return basic collection stats (chunk count, distinct documents)."""
    col = _get_collection(cfg)
    try:
        count = col.count()
        got = col.get(include=["metadatas"])
        hashes = {(m or {}).get("doc_hash") for m in (got.get("metadatas") or [])}
        hashes.discard(None)
        return {"chunks": count, "documents": len(hashes)}
    except Exception:
        return {"chunks": 0, "documents": 0}
