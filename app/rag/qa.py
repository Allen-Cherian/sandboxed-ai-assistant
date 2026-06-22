"""Extractive, grounded question answering (fully local, no LLM in V1).

V1 deliberately uses **extractive** answering: it composes an answer from the
highest-scoring retrieved chunks and always shows their sources. It does NOT
generate free-form text with a language model. This is an honest design choice for
a fully-local, zero-credential demo, and it also narrows the prompt-injection
surface — chunks are quoted as evidence, not fed to a generative model that could
be steered by them. (LLM-backed answering is a documented future extension.)

See ``docs/security_model.md`` §8 (limitations) and ``implementation_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Config
from app.tools.allowed_tools import call_tool

# Below this similarity, a chunk is considered too weak to present as an answer.
_MIN_SCORE = 0.20


@dataclass
class Answer:
    text: str
    sources: list[dict] = field(default_factory=list)
    grounded: bool = True  # False when nothing relevant was found


def answer_question(question: str, cfg: Config) -> Answer:
    """Answer ``question`` using only retrieved document chunks."""

    question = (question or "").strip()
    if not question:
        return Answer(text="Please enter a question.", grounded=False)

    # Retrieval goes through the explicit tool boundary — not a direct call.
    chunks = call_tool("retrieve_chunks", cfg, query=question)["results"]
    relevant = [c for c in chunks if c.get("score", 0.0) >= _MIN_SCORE]

    if not relevant:
        return Answer(
            text=(
                "I couldn't find anything relevant to that question in the uploaded "
                "documents. Try rephrasing, or upload a document that covers it."
            ),
            sources=chunks,  # show what was retrieved (even if weak) for transparency
            grounded=False,
        )

    # Extractive answer: present the strongest supporting passages, attributed.
    lines = [
        "Based on the uploaded documents, the most relevant passages are:",
        "",
    ]
    for i, c in enumerate(relevant, start=1):
        snippet = _snippet(c["text"])
        lines.append(f"**{i}. {c['stored_name']}** (relevance {c['score']:.2f})")
        lines.append(f"> {snippet}")
        lines.append("")

    return Answer(text="\n".join(lines).strip(), sources=relevant, grounded=True)


def _snippet(text: str, max_chars: int = 600) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " …"
