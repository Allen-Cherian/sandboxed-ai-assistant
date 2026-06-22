"""Tests for the dependency-free RAG text path: loaders (txt/md) + splitter.

These avoid the heavy ML deps (sentence-transformers/chromadb) so they run fast
and offline; embedding/vector-store behavior is exercised at container runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Config
from app.rag import loaders, splitter


def make_cfg(tmp_path: Path, chunk_size=120, overlap=30) -> Config:
    data = tmp_path / "data"
    (data / "uploads").mkdir(parents=True)
    return Config(
        data_dir=data.resolve(),
        uploads_dir=(data / "uploads").resolve(),
        chroma_dir=(data / "chroma").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        model_cache_dir=(data / "model_cache").resolve(),
        allowed_extensions=frozenset({".txt", ".md", ".pdf"}),
        max_upload_mb=1,
        embedding_model="all-MiniLM-L6-v2",
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        retrieval_top_k=4,
        app_env="test",
        log_level="INFO",
    )


# --- loaders ------------------------------------------------------------------

def test_load_txt(tmp_path):
    cfg = make_cfg(tmp_path)
    p = cfg.uploads_dir / "a.txt"
    p.write_text("hello world", encoding="utf-8")
    assert loaders.load_document(str(p), cfg) == "hello world"


def test_load_rejects_outside_data_dir(tmp_path):
    cfg = make_cfg(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(Exception):  # FilePolicyError from ensure_within_data_dir
        loaders.load_document(str(outside), cfg)


def test_load_empty_raises(tmp_path):
    cfg = make_cfg(tmp_path)
    p = cfg.uploads_dir / "empty.txt"
    p.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(loaders.LoaderError):
        loaders.load_document(str(p), cfg)


def test_load_unsupported_type(tmp_path):
    cfg = make_cfg(tmp_path)
    p = cfg.uploads_dir / "x.csv"
    p.write_text("a,b,c", encoding="utf-8")
    with pytest.raises(loaders.LoaderError):
        loaders.load_document(str(p), cfg)


# --- splitter -----------------------------------------------------------------

def test_split_empty_returns_nothing(tmp_path):
    cfg = make_cfg(tmp_path)
    assert splitter.split_text("   ", cfg) == []


def test_split_short_text_one_chunk(tmp_path):
    cfg = make_cfg(tmp_path)
    chunks = splitter.split_text("a short doc", cfg)
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "a short doc"


def test_split_long_text_multiple_chunks_with_indices(tmp_path):
    cfg = make_cfg(tmp_path, chunk_size=100, overlap=20)
    text = "\n\n".join(f"Paragraph number {i} with some filler words here." for i in range(20))
    chunks = splitter.split_text(text, cfg)
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text) <= 100 + 100 for c in chunks)  # generous upper bound


def test_split_hardwraps_oversized_paragraph(tmp_path):
    cfg = make_cfg(tmp_path, chunk_size=50, overlap=0)
    text = "x" * 240  # single paragraph, no breaks
    chunks = splitter.split_text(text, cfg)
    assert len(chunks) >= 4
    assert all(len(c.text) <= 50 for c in chunks)
