"""Concrete implementations of the assistant's allowed capabilities.

These are the ONLY actions the assistant is permitted to take. Each is a narrow,
read-only operation over the indexed documents. None of them accept a filesystem
path, run a shell, evaluate code, or reach the network.

They are registered in ``allowed_tools.py``; nothing here is callable by the
assistant except through that registry.
"""

from __future__ import annotations

from app.config import Config
from app.rag.retriever import retrieve
from app.security.file_policy import list_upload_files
from app.rag.vector_store import stats


def list_documents(cfg: Config) -> dict:
    """List the documents available to the assistant.

    Read-only. Returns names + sizes from the uploads area (boundary-checked by
    ``list_upload_files``) plus index stats. Takes no caller-supplied path.
    """
    files = list_upload_files(cfg)
    index = stats(cfg)
    return {
        "documents": [
            {"name": f["stored_name"], "size_bytes": f["size_bytes"]} for f in files
        ],
        "count": len(files),
        "indexed_documents": index.get("documents", 0),
        "indexed_chunks": index.get("chunks", 0),
    }


def retrieve_chunks(cfg: Config, *, query: str, top_k: int | None = None) -> dict:
    """Retrieve the most relevant document chunks for ``query``.

    Read-only. The only inputs are a query string and an optional result count;
    there is no way to address the filesystem or escape the document store.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("'query' must be a non-empty string.")

    if top_k is not None:
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("'top_k' must be a positive integer.")
        top_k = min(top_k, 20)  # hard ceiling — bounds work per call

    results = retrieve(query.strip(), cfg, top_k=top_k)
    return {"query": query.strip(), "results": results, "count": len(results)}
