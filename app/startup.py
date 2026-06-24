"""Startup / preflight: create required directories and validate the environment.

Run once when the app boots. Creates the writable data + log directories (the
only locations the app is permitted to write), points the model cache into the
writable volume, configures logging, and surfaces any configuration problems
clearly. See ``docs/implementation_plan.md`` Phase 1.
"""

from __future__ import annotations

import os

from app.config import Config, ConfigError, get_config
from app.logger import audit, setup_logging


def _ensure_dirs(cfg: Config) -> None:
    for d in (cfg.data_dir, cfg.uploads_dir, cfg.chroma_dir, cfg.logs_dir, cfg.model_cache_dir):
        d.mkdir(parents=True, exist_ok=True)


def _redirect_caches(cfg: Config) -> None:
    """Keep all model/library caches inside the writable volume.

    Necessary because the container root filesystem is read-only; without this,
    sentence-transformers/huggingface would try to write to ``~/.cache`` and fail.
    """

    cache = str(cfg.model_cache_dir)
    os.environ.setdefault("HF_HOME", cache)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", cache)
    os.environ.setdefault("XDG_CACHE_HOME", cache)


def run_startup() -> Config:
    """Perform preflight and return the validated config.

    Raises :class:`ConfigError` (already a clear message) on bad configuration.
    """

    cfg = get_config()
    _ensure_dirs(cfg)
    _redirect_caches(cfg)
    setup_logging(cfg.logs_dir, cfg.log_level)

    audit(
        "app_startup",
        app_env=cfg.app_env,
        data_dir=str(cfg.data_dir),
        logs_dir=str(cfg.logs_dir),
        embedding_model=cfg.embedding_model,
        allowed_extensions=sorted(cfg.allowed_extensions),
        max_upload_mb=cfg.max_upload_mb,
        retrieval_top_k=cfg.retrieval_top_k,
        llm_enabled=cfg.llm_enabled,
        llm_provider=cfg.llm_provider if cfg.llm_enabled else None,
        llm_model=cfg.llm_model if cfg.llm_enabled else None,
    )

    if cfg.llm_enabled:
        _check_llm_reachable(cfg)

    return cfg


def _check_llm_reachable(cfg: Config) -> None:
    """Non-blocking reachability probe for the configured LLM backend.

    Logs status only — NEVER raises. If the LLM is unreachable the app still runs
    fully (extractive mode); the UI degrades gracefully. This just surfaces a clear
    signal in the logs so a misconfigured/offline Ollama is easy to diagnose.
    """
    try:
        from app.rag.llm import provider_health

        ok, detail = provider_health(cfg)
    except Exception as exc:  # provider layer not present yet / import issue
        audit("llm_health", reachable=False, provider=cfg.llm_provider, detail=str(exc))
        return
    audit("llm_health", reachable=ok, provider=cfg.llm_provider, detail=detail)


__all__ = ["run_startup", "ConfigError"]
