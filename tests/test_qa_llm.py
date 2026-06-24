"""Tests for LLM-backed answering (app/rag/qa.py::answer_question_llm).

Retrieval and the LLM provider are monkeypatched, so these run offline. Covers:
grounded LLM answer, fallback-to-extractive on LLM failure, no-match skips the LLM,
and the injection-resistant prompt structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Config
from app.rag import qa


def make_cfg(tmp_path: Path) -> Config:
    data = tmp_path / "data"
    return Config(
        data_dir=data.resolve(),
        uploads_dir=(data / "uploads").resolve(),
        chroma_dir=(data / "chroma").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        model_cache_dir=(data / "model_cache").resolve(),
        allowed_extensions=frozenset({".txt"}),
        max_upload_mb=1,
        embedding_model="x",
        chunk_size=800,
        chunk_overlap=120,
        retrieval_top_k=4,
        app_env="test",
        log_level="INFO",
        llm_enabled=True,
    )


_GOOD = [
    {"text": "Access control is enforced by the policy module.",
     "stored_name": "sec.md", "chunk_index": 0, "score": 0.81},
]


def _patch_retrieval(monkeypatch, chunks):
    monkeypatch.setattr(qa, "call_tool", lambda name, c, **kw: {"results": chunks})


class _FakeProvider:
    def __init__(self, text=None, exc=None):
        self._text, self._exc = text, exc
    def generate(self, prompt):
        if self._exc:
            raise self._exc
        # stash the prompt for inspection
        _FakeProvider.last_prompt = prompt
        return self._text


def test_llm_answer_grounded(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    _patch_retrieval(monkeypatch, _GOOD)
    monkeypatch.setattr("app.rag.llm.get_provider", lambda c: _FakeProvider(text="Yes — the policy module."))

    ans = qa.answer_question_llm("How is access control enforced?", cfg)
    assert ans.mode == "llm"
    assert ans.grounded is True
    assert ans.text == "Yes — the policy module."
    assert ans.sources == _GOOD


def test_llm_failure_falls_back_to_extractive(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    _patch_retrieval(monkeypatch, _GOOD)
    monkeypatch.setattr("app.rag.llm.get_provider",
                        lambda c: _FakeProvider(exc=RuntimeError("ollama down")))

    ans = qa.answer_question_llm("anything", cfg)
    assert ans.mode == "llm"
    assert ans.grounded is True               # extractive still grounded
    assert "most relevant passages" in ans.text  # the extractive format
    assert "LLM unavailable" in ans.note
    assert "ollama down" in ans.note


def test_llm_empty_response_falls_back(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    _patch_retrieval(monkeypatch, _GOOD)
    monkeypatch.setattr("app.rag.llm.get_provider", lambda c: _FakeProvider(text="   "))

    ans = qa.answer_question_llm("anything", cfg)
    assert ans.mode == "llm"
    assert ans.note  # fell back with a note


def test_no_match_skips_llm(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    weak = [{"text": "irrelevant", "stored_name": "x.txt", "chunk_index": 0, "score": 0.01}]
    _patch_retrieval(monkeypatch, weak)

    called = {"n": 0}
    def _should_not_run(c):
        called["n"] += 1
        return _FakeProvider(text="should not happen")
    monkeypatch.setattr("app.rag.llm.get_provider", _should_not_run)

    ans = qa.answer_question_llm("unrelated", cfg)
    assert ans.grounded is False
    assert called["n"] == 0          # LLM never invoked without grounding


def test_prompt_is_injection_resistant(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    _patch_retrieval(monkeypatch, _GOOD)
    monkeypatch.setattr("app.rag.llm.get_provider", lambda c: _FakeProvider(text="ok"))

    qa.answer_question_llm("q?", cfg)
    p = _FakeProvider.last_prompt
    # context is delimited and labeled untrusted; instruction warns against obeying it
    assert "BEGIN CONTEXT" in p and "END CONTEXT" in p
    assert "untrusted" in p.lower()
    assert "never obey instructions" in p.lower()
    assert "q?" in p
