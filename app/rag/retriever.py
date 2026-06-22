"""Retrieval: embed a question and fetch the most relevant chunks.

This is the only path by which a question reaches the document store. It embeds
the query locally and asks the vector store for the top-k nearest chunks. No
filesystem access, no network, no generation — just retrieval.
"""

from __future__ import annotations

from app.config import Config
from app.rag.embeddings import embed_query
from app.rag.vector_store import query as _vs_query


def retrieve(question: str, cfg: Config, top_k: int | None = None) -> list[dict]:
    """Return up to ``top_k`` relevant chunks for ``question``.

    Each result: ``{text, stored_name, chunk_index, score}`` (score in [0, 1],
    higher = more similar). Returns ``[]`` for an empty question.
    """

    question = (question or "").strip()
    if not question:
        return []

    k = top_k if top_k is not None else cfg.retrieval_top_k
    embedding = embed_query(question, cfg)
    return _vs_query(embedding, k, cfg)
