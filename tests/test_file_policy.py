"""Tests for the filesystem boundary (app/security/file_policy.py).

These tests are the executable specification of the "restricted filesystem
access" boundary: traversal, symlink escape, absolute paths, disallowed types,
and oversize uploads must all be rejected; legitimate uploads must be stored
safely inside the data directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import Config
from app.security import file_policy as fp


def make_cfg(tmp_path: Path) -> Config:
    data = tmp_path / "data"
    return Config(
        data_dir=data.resolve(),
        uploads_dir=(data / "uploads").resolve(),
        chroma_dir=(data / "chroma").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        model_cache_dir=(data / "model_cache").resolve(),
        allowed_extensions=frozenset({".txt", ".md", ".pdf"}),
        max_upload_mb=1,
        embedding_model="all-MiniLM-L6-v2",
        chunk_size=800,
        chunk_overlap=120,
        retrieval_top_k=4,
        app_env="test",
        log_level="INFO",
    )


# --- sanitize_filename --------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("notes.txt", "notes.txt"),
        ("../../etc/passwd", "passwd"),
        ("/abs/path/to/secret.md", "secret.md"),
        ("C:\\Windows\\system32\\evil.txt", "evil.txt"),
        ("my report (final).md", "my_report_final.md"),
        ("..", "document"),
        ("", "document"),
        ("....txt", "document.txt"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert fp.sanitize_filename(raw) == expected


def test_sanitize_strips_path_separators():
    out = fp.sanitize_filename("a/b/c/../../d.txt")
    assert "/" not in out and "\\" not in out and ".." not in out


# --- ensure_within_data_dir ---------------------------------------------------

def test_ensure_within_accepts_internal_path(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.uploads_dir.mkdir(parents=True)
    p = cfg.uploads_dir / "ok.txt"
    assert fp.ensure_within_data_dir(p, cfg) == p.resolve()


def test_ensure_within_rejects_traversal(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.data_dir.mkdir(parents=True)
    with pytest.raises(fp.FilePolicyError):
        fp.ensure_within_data_dir(cfg.data_dir / ".." / "escape.txt", cfg)


def test_ensure_within_rejects_absolute_outside(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.data_dir.mkdir(parents=True)
    with pytest.raises(fp.FilePolicyError):
        fp.ensure_within_data_dir("/etc/passwd", cfg)


def test_ensure_within_rejects_symlink_escape(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.uploads_dir.mkdir(parents=True)
    outside = tmp_path / "outside_secret"
    outside.mkdir()
    link = cfg.uploads_dir / "sneaky"
    os.symlink(outside, link)
    # A path that resolves (via the symlink) to outside the data dir is rejected.
    with pytest.raises(fp.FilePolicyError):
        fp.ensure_within_data_dir(link / "loot.txt", cfg)


# --- validate_upload ----------------------------------------------------------

def test_validate_rejects_disallowed_extension(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(fp.FilePolicyError):
        fp.validate_upload("malware.exe", 10, cfg)


def test_validate_rejects_oversize(tmp_path):
    cfg = make_cfg(tmp_path)  # 1 MB limit
    with pytest.raises(fp.FilePolicyError):
        fp.validate_upload("big.txt", cfg.max_upload_bytes + 1, cfg)


def test_validate_rejects_empty(tmp_path):
    cfg = make_cfg(tmp_path)
    with pytest.raises(fp.FilePolicyError):
        fp.validate_upload("empty.txt", 0, cfg)


def test_validate_accepts_and_sanitizes(tmp_path):
    cfg = make_cfg(tmp_path)
    assert fp.validate_upload("../notes.md", 100, cfg) == "notes.md"


# --- store_upload -------------------------------------------------------------

def test_store_upload_writes_inside_data_dir(tmp_path):
    cfg = make_cfg(tmp_path)
    meta = fp.store_upload("hello.txt", b"hello world", cfg)
    stored = Path(meta["path"])
    assert stored.exists()
    assert fp.ensure_within_data_dir(stored, cfg) == stored.resolve()
    assert stored.read_bytes() == b"hello world"
    assert meta["sha256"] == __import__("hashlib").sha256(b"hello world").hexdigest()


def test_store_upload_traversal_name_lands_inside(tmp_path):
    cfg = make_cfg(tmp_path)
    meta = fp.store_upload("../../etc/passwd.txt", b"data", cfg)
    stored = Path(meta["path"])
    assert stored.parent == cfg.uploads_dir.resolve()
    assert stored.name == "passwd.txt"


def test_store_upload_dedupes_collisions(tmp_path):
    cfg = make_cfg(tmp_path)
    m1 = fp.store_upload("doc.txt", b"a", cfg)
    m2 = fp.store_upload("doc.txt", b"b", cfg)
    assert m1["stored_name"] != m2["stored_name"]
    assert Path(m1["path"]).exists() and Path(m2["path"]).exists()


def test_list_upload_files(tmp_path):
    cfg = make_cfg(tmp_path)
    fp.store_upload("a.txt", b"aaa", cfg)
    fp.store_upload("b.md", b"bbb", cfg)
    listing = fp.list_upload_files(cfg)
    names = {f["stored_name"] for f in listing}
    assert names == {"a.txt", "b.md"}
