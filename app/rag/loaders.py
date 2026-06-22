"""Document loaders for supported file types (.txt, .md, .pdf).

Loaders read ONLY from paths that have already passed the filesystem boundary
(`app/security/file_policy`). They extract plain text — they never execute
embedded content (e.g. PDF JavaScript) and never follow external references.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Config
from app.security.file_policy import ensure_within_data_dir


class LoaderError(Exception):
    """Raised when a document cannot be loaded or has an unsupported type."""


def _read_text(path: Path) -> str:
    # errors="replace" so a stray bad byte never crashes ingestion.
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LoaderError("PDF support requires the 'pypdf' package.") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            # A single unreadable page shouldn't abort the whole document.
            parts.append("")
    return "\n\n".join(parts)


_LOADERS = {
    ".txt": _read_text,
    ".md": _read_text,
    ".pdf": _read_pdf,
}


def load_document(path: str, cfg: Config) -> str:
    """Load a document's plain text, enforcing the filesystem boundary first.

    Raises :class:`LoaderError` for unsupported types or empty extraction.
    """

    safe_path = ensure_within_data_dir(path, cfg)
    if not safe_path.is_file():
        raise LoaderError(f"Not a file: {safe_path.name}")

    ext = safe_path.suffix.lower()
    loader = _LOADERS.get(ext)
    if loader is None:
        raise LoaderError(f"Unsupported file type: {ext}")

    text = loader(safe_path).strip()
    if not text:
        raise LoaderError(
            f"No extractable text found in {safe_path.name} "
            "(scanned/image-only PDFs are not supported in V1)."
        )
    return text
