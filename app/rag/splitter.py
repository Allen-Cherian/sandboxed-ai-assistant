"""Text chunking.

A small, dependency-free splitter. It first normalizes whitespace, then splits on
paragraph boundaries where possible, packing paragraphs into windows of
~``chunk_size`` characters with ``chunk_overlap`` carried between consecutive
chunks. Overlap preserves context that straddles a boundary so retrieval quality
holds up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Config


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int  # position of this chunk within its document (0-based)


_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _hard_wrap(segment: str, size: int) -> list[str]:
    """Split an over-long segment that has no paragraph break to lean on."""
    return [segment[i : i + size] for i in range(0, len(segment), size)]


def split_text(text: str, cfg: Config) -> list[Chunk]:
    """Split ``text`` into overlapping chunks according to config."""

    size = cfg.chunk_size
    overlap = cfg.chunk_overlap
    normalized = _normalize(text)
    if not normalized:
        return []

    # Candidate units: paragraphs; hard-wrap any paragraph bigger than `size`.
    units: list[str] = []
    for para in normalized.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        units.extend(_hard_wrap(para, size) if len(para) > size else [para])

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + 1 + len(unit) <= size:
            current = f"{current}\n{unit}"
        else:
            chunks.append(current)
            # Start the next chunk with an overlap tail of the previous one.
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n{unit}".strip() if tail else unit
    if current:
        chunks.append(current)

    return [Chunk(text=c, index=i) for i, c in enumerate(chunks)]
