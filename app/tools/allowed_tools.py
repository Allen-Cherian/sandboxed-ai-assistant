"""Explicit tool/capability allow-list — the least-privilege boundary.

This module is the *only* way any caller (the UI today, an LLM agent in the
future) is permitted to act on documents. It implements **deny by default**: a
tool name that is not in the registry cannot be invoked. Adding a capability is a
deliberate, single-location code change — capabilities can never appear
implicitly.

The assistant has NO access to a shell, ``eval``/``exec``, arbitrary filesystem
read/write, the network, or plugin loading. The entire surface is the two tools
registered below.

See ``docs/security_model.md`` §4 (Tool / Capability Boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.config import Config
from app.logger import audit
from app.tools import document_tools


class ToolNotAllowedError(Exception):
    """Raised when a caller requests a tool that is not in the allow-list."""


class ToolExecutionError(Exception):
    """Raised when an allowed tool fails or is called with invalid arguments."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    func: Callable[..., dict]
    # JSON-schema-style description of accepted params (also documents the
    # surface for a future LLM tool-use integration).
    parameters: dict


# ---------------------------------------------------------------------------
# THE ALLOW-LIST. This is the complete set of capabilities the assistant has.
# To add a capability you must add an entry here *and* implement it in
# document_tools.py. There is no other path.
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, Tool] = {
    "list_documents": Tool(
        name="list_documents",
        description="List the documents available to the assistant and index stats.",
        func=document_tools.list_documents,
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    "retrieve_chunks": Tool(
        name="retrieve_chunks",
        description="Retrieve the most relevant document chunks for a query.",
        func=document_tools.retrieve_chunks,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "top_k": {"type": "integer", "description": "Max chunks (1-20)."},
            },
            "required": ["query"],
        },
    ),
}

# Parameter names each tool is allowed to receive. Any other keyword is rejected
# before the tool runs — callers cannot smuggle in unexpected arguments.
_ALLOWED_PARAMS: dict[str, set[str]] = {
    "list_documents": set(),
    "retrieve_chunks": {"query", "top_k"},
}


def available_tools() -> list[dict]:
    """Return the public descriptions of allowed tools (no callables)."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in _REGISTRY.values()
    ]


def is_allowed(name: str) -> bool:
    return name in _REGISTRY


def call_tool(name: str, cfg: Config, **kwargs: Any) -> dict:
    """Dispatch a tool call through the allow-list (deny by default).

    Raises :class:`ToolNotAllowedError` for unknown tools and
    :class:`ToolExecutionError` for bad arguments or execution failures. Every
    call — allowed or denied — is audited.
    """
    tool = _REGISTRY.get(name)
    if tool is None:
        audit("tool_denied", tool=name, reason="not_in_allow_list")
        raise ToolNotAllowedError(
            f"Tool {name!r} is not allowed. Available: {sorted(_REGISTRY)}."
        )

    # Reject unexpected keyword arguments (deny by default at the param level too).
    extra = set(kwargs) - _ALLOWED_PARAMS[name]
    if extra:
        audit("tool_denied", tool=name, reason="unexpected_params", params=sorted(extra))
        raise ToolExecutionError(
            f"Tool {name!r} received unexpected parameters: {sorted(extra)}."
        )

    audit("tool_invoked", tool=name, params=sorted(kwargs))
    try:
        result = tool.func(cfg, **kwargs)
    except (ValueError, TypeError) as exc:
        audit("tool_error", tool=name, reason=str(exc))
        raise ToolExecutionError(f"Tool {name!r} failed: {exc}") from exc
    return result
