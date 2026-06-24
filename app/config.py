"""Environment-based configuration for the sandboxed AI assistant.

All configuration is loaded from environment variables (optionally via a `.env`
file in development). There are NO hardcoded secrets and V1 requires no
credentials. This module is the single place configuration is read and validated,
so the secret-handling boundary lives here.

See ``docs/security_model.md`` §5 (Secret Handling Model).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

# Providers the factory knows about. Only "ollama" is implemented this phase;
# the others are documented slots (see docs/phase_llm_plan.md §10).
_KNOWN_PROVIDERS = {"ollama", "anthropic", "openai"}

# Optional: load a local .env in development. In the container, real environment
# variables are used and python-dotenv simply finds nothing to load.
try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional; never fail because of it
    pass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"Environment variable {name!r} must be an integer, got {raw!r}")


class ConfigError(Exception):
    """Raised when configuration is missing or malformed."""


@dataclass(frozen=True)
class Config:
    """Resolved, validated application configuration."""

    # --- Filesystem boundary ---
    # DATA_DIR is the ONLY directory the app is permitted to write to (plus logs).
    data_dir: Path
    uploads_dir: Path
    chroma_dir: Path
    logs_dir: Path
    # Where huggingface / sentence-transformers cache models. Kept inside the
    # writable volume so the read-only root filesystem is never written to.
    model_cache_dir: Path

    # --- Upload policy ---
    allowed_extensions: frozenset[str]
    max_upload_mb: int

    # --- RAG parameters ---
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int

    # --- App / logging ---
    app_env: str
    log_level: str

    # --- Optional local LLM (answering backend; default OFF) ---
    # When disabled the app is byte-for-byte V1 (extractive, no egress, no model).
    # Defaulted so existing constructors (and tests) need not specify them.
    llm_enabled: bool = False
    llm_provider: str = "ollama"   # "ollama" (built) | "anthropic"/"openai" (slots)
    llm_model: str = "llama3.2:1b" # swappable, no code change
    llm_base_url: str = "http://host.docker.internal:11434"  # ONLY network target
    llm_timeout_s: int = 30        # hard timeout — bounds a slow/runaway generation
    llm_max_tokens: int = 512      # response size cap — bounds output

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_config() -> Config:
    """Build a :class:`Config` from the environment and validate it."""

    data_dir = Path(os.getenv("DATA_DIR", "/app/data")).resolve()
    logs_dir = Path(os.getenv("LOG_DIR", str(data_dir.parent / "logs"))).resolve()

    uploads_dir = data_dir / "uploads"
    chroma_dir = data_dir / "chroma"
    model_cache_dir = data_dir / "model_cache"

    allowed = os.getenv("ALLOWED_EXTENSIONS", ".txt,.md,.pdf")
    allowed_extensions = frozenset(
        e if e.startswith(".") else f".{e}"
        for e in (x.strip().lower() for x in allowed.split(","))
        if e
    )

    cfg = Config(
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        chroma_dir=chroma_dir,
        logs_dir=logs_dir,
        model_cache_dir=model_cache_dir,
        allowed_extensions=allowed_extensions,
        max_upload_mb=_get_int("MAX_UPLOAD_MB", 10),
        embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        chunk_size=_get_int("CHUNK_SIZE", 800),
        chunk_overlap=_get_int("CHUNK_OVERLAP", 120),
        retrieval_top_k=_get_int("RETRIEVAL_TOP_K", 4),
        llm_enabled=_get_bool("LLM_ENABLED", False),
        llm_provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
        llm_model=os.getenv("LLM_MODEL", "llama3.2:1b"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://host.docker.internal:11434").rstrip("/"),
        llm_timeout_s=_get_int("LLM_TIMEOUT_S", 30),
        llm_max_tokens=_get_int("LLM_MAX_TOKENS", 512),
        app_env=os.getenv("APP_ENV", "production"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.max_upload_mb <= 0:
        raise ConfigError("MAX_UPLOAD_MB must be a positive integer.")
    if cfg.chunk_size <= 0:
        raise ConfigError("CHUNK_SIZE must be a positive integer.")
    if not (0 <= cfg.chunk_overlap < cfg.chunk_size):
        raise ConfigError("CHUNK_OVERLAP must be >= 0 and < CHUNK_SIZE.")
    if cfg.retrieval_top_k <= 0:
        raise ConfigError("RETRIEVAL_TOP_K must be a positive integer.")
    if not cfg.allowed_extensions:
        raise ConfigError("ALLOWED_EXTENSIONS must list at least one extension.")

    # --- LLM config validation (only meaningful when enabled) ---
    if cfg.llm_enabled:
        if cfg.llm_provider not in _KNOWN_PROVIDERS:
            raise ConfigError(
                f"LLM_PROVIDER {cfg.llm_provider!r} is not recognized. "
                f"Known: {sorted(_KNOWN_PROVIDERS)}."
            )
        if not cfg.llm_model:
            raise ConfigError("LLM_MODEL must be set when LLM_ENABLED is true.")
        # The base URL is the single permitted network destination — require a
        # well-formed http(s) URL with a host, so a malformed/hostile value can't
        # be used as the call target.
        parsed = urlparse(cfg.llm_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(
                "LLM_BASE_URL must be a valid http(s) URL, e.g. "
                "http://host.docker.internal:11434."
            )
        if cfg.llm_timeout_s <= 0:
            raise ConfigError("LLM_TIMEOUT_S must be a positive integer.")
        if cfg.llm_max_tokens <= 0:
            raise ConfigError("LLM_MAX_TOKENS must be a positive integer.")


# Module-level singleton, lazily built on first import use.
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
