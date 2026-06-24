"""Tests for LLM config + the Ollama provider (Step 1/2).

HTTP is monkeypatched, so these run fully offline — no Ollama, no model needed.
Covers: config defaults, validation (only when enabled), provider selection,
and the provider's bounded/safe behavior (timeout, empty response, unreachable).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import config as config_mod
from app.config import ConfigError, load_config


# --- config -------------------------------------------------------------------

def _clear_llm_env(monkeypatch):
    for k in ("LLM_ENABLED", "LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL",
              "LLM_TIMEOUT_S", "LLM_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)


def test_llm_defaults_off(monkeypatch):
    _clear_llm_env(monkeypatch)
    cfg = load_config()
    assert cfg.llm_enabled is False
    assert cfg.llm_provider == "ollama"
    assert cfg.llm_model == "llama3.2:1b"
    assert cfg.llm_base_url.startswith("http://")


def test_unknown_provider_rejected_when_enabled(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "definitely-not-real")
    with pytest.raises(ConfigError):
        load_config()


def test_bad_base_url_rejected_when_enabled(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_BASE_URL", "not-a-url")
    with pytest.raises(ConfigError):
        load_config()


def test_bad_url_ignored_when_disabled(monkeypatch):
    # Validation of LLM fields only applies when enabled.
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("LLM_BASE_URL", "not-a-url")
    cfg = load_config()  # should not raise
    assert cfg.llm_enabled is False


# --- provider selection -------------------------------------------------------

def _cfg(**over):
    from app.config import Config
    base = dict(
        data_dir=Path("/tmp/d"), uploads_dir=Path("/tmp/d/u"), chroma_dir=Path("/tmp/d/c"),
        logs_dir=Path("/tmp/l"), model_cache_dir=Path("/tmp/d/m"),
        allowed_extensions=frozenset({".txt"}), max_upload_mb=1,
        embedding_model="x", chunk_size=800, chunk_overlap=120, retrieval_top_k=4,
        llm_enabled=True, llm_provider="ollama", llm_model="llama3.2:1b",
        llm_base_url="http://host.docker.internal:11434", llm_timeout_s=30, llm_max_tokens=512,
        app_env="test", log_level="INFO",
    )
    base.update(over)
    return Config(**base)


def test_get_provider_ollama():
    from app.rag.llm import get_provider
    from app.rag.llm.ollama_provider import OllamaProvider
    assert isinstance(get_provider(_cfg()), OllamaProvider)


def test_get_provider_unimplemented_api(monkeypatch):
    from app.rag.llm import get_provider, LLMError
    with pytest.raises(LLMError):
        get_provider(_cfg(llm_provider="anthropic"))


def test_get_provider_unknown():
    from app.rag.llm import get_provider, LLMError
    with pytest.raises(LLMError):
        get_provider(_cfg(llm_provider="nope"))


# --- Ollama provider (HTTP mocked) -------------------------------------------

class _FakeResp:
    def __init__(self, body, status=200):
        self._body = body.encode("utf-8")
        self.status = status
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_generate_returns_text(monkeypatch):
    from app.rag.llm.ollama_provider import OllamaProvider
    import app.rag.llm.ollama_provider as mod

    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp('{"response": "hello from llm"}'),
    )
    out = OllamaProvider(_cfg()).generate("hi")
    assert out == "hello from llm"


def test_generate_empty_response_raises(monkeypatch):
    from app.rag.llm.ollama_provider import OllamaProvider, LLMError
    import app.rag.llm.ollama_provider as mod

    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp('{"response": "   "}'),
    )
    with pytest.raises(LLMError):
        OllamaProvider(_cfg()).generate("hi")


def test_generate_unreachable_raises(monkeypatch):
    from app.rag.llm.ollama_provider import OllamaProvider, LLMError
    import app.rag.llm.ollama_provider as mod

    def boom(req, timeout=None):
        raise mod.urllib.error.URLError("connection refused")
    monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError):
        OllamaProvider(_cfg()).generate("hi")


def test_health_unreachable_returns_false(monkeypatch):
    from app.rag.llm.ollama_provider import OllamaProvider
    import app.rag.llm.ollama_provider as mod

    def boom(req, timeout=None):
        raise mod.urllib.error.URLError("refused")
    monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
    ok, detail = OllamaProvider(_cfg()).health()
    assert ok is False
    assert "unreachable" in detail
