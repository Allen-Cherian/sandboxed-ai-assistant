"""Tests for extractive Q&A logic (app/rag/qa.py).

The retriever is monkeypatched so these run offline without the embedding model
or vector store — we're testing the answer-composition / thresholding logic.
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
        embedding_model="all-MiniLM-L6-v2",
        chunk_size=800,
        chunk_overlap=120,
        retrieval_top_k=4,
        app_env="test",
        log_level="INFO",
    )


def test_empty_question(tmp_path):
    cfg = make_cfg(tmp_path)
    ans = qa.answer_question("   ", cfg)
    assert ans.grounded is False
    assert "enter a question" in ans.text.lower()


def test_grounded_answer_includes_sources(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    fake = [
        {"text": "Access control is enforced by the policy module.",
         "stored_name": "sec.md", "chunk_index": 0, "score": 0.81},
        {"text": "Weakly related sentence.", "stored_name": "sec.md",
         "chunk_index": 3, "score": 0.05},
    ]
    monkeypatch.setattr(qa, "call_tool", lambda name, c, **kw: {"results": fake})

    ans = qa.answer_question("How is access control enforced?", cfg)
    assert ans.grounded is True
    # Only the above-threshold chunk is presented as a source.
    assert len(ans.sources) == 1
    assert ans.sources[0]["stored_name"] == "sec.md"
    assert "access control" in ans.text.lower()


def test_no_relevant_chunks_is_ungrounded(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    fake = [{"text": "irrelevant", "stored_name": "x.txt", "chunk_index": 0, "score": 0.01}]
    monkeypatch.setattr(qa, "call_tool", lambda name, c, **kw: {"results": fake})

    ans = qa.answer_question("totally unrelated question", cfg)
    assert ans.grounded is False
    assert "couldn't find" in ans.text.lower()
    # Still surfaces what was retrieved, for transparency.
    assert ans.sources == fake


def test_snippet_truncates_long_text():
    long = "word " * 500
    out = qa._snippet(long, max_chars=100)
    assert len(out) <= 102  # 100 + " …"
    assert out.endswith("…")
