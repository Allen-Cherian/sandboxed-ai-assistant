"""Optional LLM answering backend — provider abstraction.

The LLM is a **text generator, not an agent**: it receives an already-retrieved,
grounded prompt and returns text. It is never given tools and never touches the
filesystem. Retrieval still happens through the tool allow-list *before* the LLM is
involved. See ``docs/phase_llm_plan.md`` (§3.1 boundary preservation) and
``docs/agentic_future.md``.

Provider selection is config-driven (``LLM_PROVIDER``) so the model *and* the
provider are swappable without touching the answer layer. Only ``ollama`` is
implemented this phase; ``anthropic``/``openai`` are documented slots (plan §10).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.config import Config


class LLMError(Exception):
    """Raised when an LLM provider cannot be built or a generation fails."""


class LLMProvider(ABC):
    """Common interface every provider implements. Text in → text out."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Return generated text for ``prompt`` (bounded by config timeout/size)."""

    @abstractmethod
    def health(self) -> tuple[bool, str]:
        """Return (reachable, human-readable detail). Must not raise."""


def get_provider(cfg: Config) -> LLMProvider:
    """Build the provider selected by ``cfg.llm_provider`` (deny unknown).

    Raises :class:`LLMError` for unimplemented/unknown providers so the caller can
    fall back to extractive answering with a clear message.
    """
    provider = cfg.llm_provider
    if provider == "ollama":
        from app.rag.llm.ollama_provider import OllamaProvider

        return OllamaProvider(cfg)
    if provider in {"anthropic", "openai"}:
        # Documented slot — not implemented this phase (see plan §10).
        from app.rag.llm.api_providers import unimplemented

        unimplemented(provider)
    raise LLMError(f"Unknown LLM provider: {provider!r}.")


def provider_health(cfg: Config) -> tuple[bool, str]:
    """Convenience: build the provider and probe health. Never raises."""
    try:
        return get_provider(cfg).health()
    except Exception as exc:
        return False, str(exc)


__all__ = ["LLMProvider", "LLMError", "get_provider", "provider_health"]
