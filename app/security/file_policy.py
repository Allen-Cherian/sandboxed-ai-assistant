"""Filesystem boundary enforcement.

Every filesystem access in the app routes through this module. It guarantees that
no path — whether crafted by a user, derived from an upload filename, or passed by
a tool — can escape the dedicated data directory. It also enforces the upload
policy (allowed extensions, size limit).

This is the single source of truth for the "restricted filesystem access"
boundary described in ``docs/security_model.md`` §3.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

from app.config import Config


class FilePolicyError(Exception):
    """Raised when a path or file violates the filesystem policy."""


# Characters allowed in a stored filename stem. Everything else is collapsed to
# an underscore. Keeps stored names predictable and free of path separators,
# control chars, and shell metacharacters.
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    """Reduce an arbitrary upload filename to a safe, basename-only filename.

    - strips any directory components (defends against ``../`` and absolute paths)
    - normalizes unicode and removes control characters
    - collapses disallowed characters to ``_``
    - guarantees a non-empty result
    """

    # Take basename only — kills "../../etc/passwd", "C:\\...", "/abs/path".
    base = os.path.basename(filename.replace("\\", "/"))
    base = unicodedata.normalize("NFKC", base)
    # Drop control characters.
    base = "".join(ch for ch in base if ch.isprintable())

    stem, dot, ext = base.rpartition(".")
    if not dot:  # no extension
        stem, ext = base, ""

    stem = _SAFE_STEM_RE.sub("_", stem).strip("._-")
    ext = _SAFE_STEM_RE.sub("", ext).lower()

    if not stem:
        stem = "document"
    return f"{stem}.{ext}" if ext else stem


def is_allowed_extension(filename: str, cfg: Config) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in cfg.allowed_extensions


def ensure_within_data_dir(path: str | os.PathLike[str], cfg: Config) -> Path:
    """Resolve ``path`` and assert it is contained within ``DATA_DIR``.

    Follows symlinks (``realpath``) so a symlink inside the data dir cannot point
    out of it. Raises :class:`FilePolicyError` on any escape attempt.
    """

    data_root = cfg.data_dir.resolve()
    candidate = Path(path).resolve()

    # Python 3.9+: is_relative_to. Use commonpath as an explicit, audit-friendly check.
    try:
        common = os.path.commonpath([str(data_root), str(candidate)])
    except ValueError:
        # Different drives (Windows) → definitely outside.
        raise FilePolicyError(f"Path escapes data directory: {candidate}")

    if common != str(data_root):
        raise FilePolicyError(f"Path escapes data directory: {candidate}")
    return candidate


def validate_upload(filename: str, size_bytes: int, cfg: Config) -> str:
    """Validate an incoming upload against the policy.

    Returns the safe stored filename. Raises :class:`FilePolicyError` if the
    extension is not allowed or the file is too large.
    """

    if size_bytes <= 0:
        raise FilePolicyError("Uploaded file is empty.")
    if size_bytes > cfg.max_upload_bytes:
        raise FilePolicyError(
            f"File too large: {size_bytes} bytes (limit {cfg.max_upload_mb} MB)."
        )

    safe_name = sanitize_filename(filename)
    if not is_allowed_extension(safe_name, cfg):
        allowed = ", ".join(sorted(cfg.allowed_extensions))
        raise FilePolicyError(
            f"File type not allowed. Allowed extensions: {allowed}."
        )
    return safe_name


def _dedupe_path(directory: Path, filename: str) -> Path:
    """Return a non-colliding path inside ``directory`` for ``filename``."""

    target = directory / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    ext = Path(filename).suffix
    i = 1
    while True:
        candidate = directory / f"{stem}_{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def store_upload(filename: str, content: bytes, cfg: Config) -> dict:
    """Validate and persist an upload into ``uploads/`` inside the data dir.

    Returns metadata about the stored file. Every path is re-checked with
    :func:`ensure_within_data_dir` before writing — defense in depth.
    """

    safe_name = validate_upload(filename, len(content), cfg)

    cfg.uploads_dir.mkdir(parents=True, exist_ok=True)
    target = _dedupe_path(cfg.uploads_dir, safe_name)

    # Final boundary assertion before any write touches the disk.
    target = ensure_within_data_dir(target, cfg)

    sha256 = hashlib.sha256(content).hexdigest()

    # Exclusive create where possible; never follow a pre-existing symlink.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
    except Exception:
        # Clean up a partial file on failure.
        try:
            os.unlink(target)
        except OSError:
            pass
        raise

    return {
        "stored_name": target.name,
        "original_name": filename,
        "path": str(target),
        "size_bytes": len(content),
        "sha256": sha256,
        "extension": target.suffix.lower(),
    }


def list_upload_files(cfg: Config) -> list[dict]:
    """List stored upload files (name + size). Read-only, boundary-checked."""

    uploads = cfg.uploads_dir
    if not uploads.exists():
        return []
    out: list[dict] = []
    for p in sorted(uploads.iterdir()):
        if p.name == ".gitkeep" or not p.is_file():
            continue
        # Re-assert containment for every path we surface.
        ensure_within_data_dir(p, cfg)
        out.append({"stored_name": p.name, "size_bytes": p.stat().st_size})
    return out
