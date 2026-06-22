"""Tests for the explicit tool/capability boundary (app/tools/allowed_tools.py).

The security-critical guarantees:
  * exactly two tools are registered (no more)
  * unknown tools are denied (deny by default)
  * unexpected parameters are rejected
  * allowed tools dispatch to their implementation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Config
from app.tools import allowed_tools as at


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


def test_registry_is_exactly_the_two_allowed_tools():
    names = {t["name"] for t in at.available_tools()}
    assert names == {"list_documents", "retrieve_chunks"}


def test_available_tools_exposes_no_callables():
    for t in at.available_tools():
        assert set(t) == {"name", "description", "parameters"}
        assert "func" not in t


@pytest.mark.parametrize("bad", ["run_shell", "read_file", "eval", "list_documentss", ""])
def test_unknown_tool_is_denied(tmp_path, bad):
    cfg = make_cfg(tmp_path)
    with pytest.raises(at.ToolNotAllowedError):
        at.call_tool(bad, cfg)


def test_unexpected_param_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(at.ToolExecutionError):
        at.call_tool("retrieve_chunks", cfg, query="hi", path="/etc/passwd")


def test_list_documents_dispatches(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.uploads_dir.mkdir(parents=True)
    # Avoid touching the vector store in this unit test.
    monkeypatch.setattr(at.document_tools, "stats", lambda c: {"documents": 0, "chunks": 0})
    out = at.call_tool("list_documents", cfg)
    assert out["count"] == 0
    assert out["documents"] == []


def test_retrieve_chunks_validates_query(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(at.ToolExecutionError):
        at.call_tool("retrieve_chunks", cfg, query="   ")


def test_retrieve_chunks_dispatches(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    fake = [{"text": "x", "stored_name": "a.txt", "chunk_index": 0, "score": 0.9}]
    monkeypatch.setattr(at.document_tools, "retrieve", lambda q, c, top_k=None: fake)
    out = at.call_tool("retrieve_chunks", cfg, query="hello")
    assert out["count"] == 1
    assert out["results"] == fake
    assert out["query"] == "hello"
