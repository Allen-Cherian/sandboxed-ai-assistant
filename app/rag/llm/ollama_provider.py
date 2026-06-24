"""Ollama provider — calls a local Ollama server (host or sidecar).

Fully local: the only network destination is ``cfg.llm_base_url`` (default the host
Ollama at ``host.docker.internal:11434``). Security properties enforced here:

- **Single, config-controlled destination.** The request URL is built only from
  ``cfg.llm_base_url`` — never from user input or document content.
- **Hard timeout** (``cfg.llm_timeout_s``) so a slow/runaway generation can't hang
  the app.
- **Response size cap** (``cfg.llm_max_tokens``) so output is bounded.
- Uses the Python standard library (``urllib``) — no extra dependency, no client
  that could silently reach elsewhere.

The provider only sends a prompt and returns text. It has no tools and no filesystem
access.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import Config
from app.rag.llm import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, cfg: Config) -> None:
        self._base_url = cfg.llm_base_url.rstrip("/")
        self._model = cfg.llm_model
        self._timeout = cfg.llm_timeout_s
        self._max_tokens = cfg.llm_max_tokens

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": self._max_tokens},
        }
        data = self._post("/api/generate", payload)
        text = (data or {}).get("response", "")
        if not isinstance(text, str) or not text.strip():
            raise LLMError("LLM returned an empty response.")
        return text.strip()

    def health(self) -> tuple[bool, str]:
        """Probe the Ollama server root. Never raises."""
        try:
            req = urllib.request.Request(self._base_url + "/", method="GET")
            with urllib.request.urlopen(req, timeout=min(self._timeout, 5)) as resp:
                return (resp.status == 200), f"ollama at {self._base_url} (HTTP {resp.status})"
        except urllib.error.URLError as exc:
            return False, f"ollama unreachable at {self._base_url}: {exc.reason}"
        except Exception as exc:  # belt-and-suspenders — health must not raise
            return False, f"ollama check failed: {exc}"

    # --- internal ---------------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        url = self._base_url + path
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise LLMError(f"LLM HTTP {exc.code} from {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"LLM unreachable at {url}: {exc.reason}. Is Ollama running?"
            ) from exc
        except TimeoutError as exc:
            raise LLMError(f"LLM timed out after {self._timeout}s.") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {exc}") from exc
