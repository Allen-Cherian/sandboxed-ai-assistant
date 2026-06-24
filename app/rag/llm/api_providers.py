"""API provider slots (Anthropic / OpenAI) — NOT implemented this phase.

These are intentionally empty. The provider abstraction reserves the slots so that
adding a cloud LLM later is a drop-in (one class + a factory line + an env key),
with NO change to the answer layer, UI, retrieval, or security boundaries.

See ``docs/phase_llm_plan.md`` §10 for the exact recipe, and note the trade-off:
an API provider means document text leaves the machine, which must be a conscious,
documented opt-in (it breaks the fully-local / no-egress property).
"""

from __future__ import annotations

from app.rag.llm import LLMError


def unimplemented(provider: str) -> None:
    """Raise a clear, actionable error for a reserved-but-unbuilt provider."""
    raise LLMError(
        f"LLM provider {provider!r} is a reserved slot but is not implemented yet. "
        f"Use LLM_PROVIDER=ollama (fully local), or implement it per "
        f"docs/phase_llm_plan.md §10. Note: an API provider sends document text "
        f"off-machine and must be a deliberate opt-in."
    )
