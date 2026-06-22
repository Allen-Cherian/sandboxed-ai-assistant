"""Local embedding generation (fully offline).

Wraps a sentence-transformers model. The model is loaded once and cached; the
model files live inside the writable data volume (`model_cache/`) so the
read-only container root filesystem is never written to (see
`app/startup._redirect_caches`).

V1 makes NO network calls at inference time and requires NO credentials.
"""

from __future__ import annotations

import threading

from app.config import Config

_model = None
_model_name: str | None = None
_lock = threading.Lock()


class EmbeddingError(Exception):
    """Raised when the embedding model cannot be loaded or used."""


def _get_model(cfg: Config):
    """Lazily load (and memoize) the sentence-transformers model."""
    global _model, _model_name
    if _model is not None and _model_name == cfg.embedding_model:
        return _model
    with _lock:
        if _model is not None and _model_name == cfg.embedding_model:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise EmbeddingError(
                "Embeddings require the 'sentence-transformers' package."
            ) from exc
        try:
            _model = SentenceTransformer(
                cfg.embedding_model, cache_folder=str(cfg.model_cache_dir)
            )
            _model_name = cfg.embedding_model
        except Exception as exc:
            raise EmbeddingError(
                f"Could not load embedding model {cfg.embedding_model!r}: {exc}"
            ) from exc
    return _model


def embed_texts(texts: list[str], cfg: Config) -> list[list[float]]:
    """Embed a batch of texts into vectors."""
    if not texts:
        return []
    model = _get_model(cfg)
    vectors = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str, cfg: Config) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text], cfg)[0]
