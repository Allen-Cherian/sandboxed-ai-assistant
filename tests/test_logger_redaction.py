"""Tests for secret redaction in the audit logger (app/logger.py).

Guarantees the documented patterns (*_KEY, *_TOKEN, *_SECRET, PASSWORD) are
redacted, including nested structures, and that ordinary fields pass through.
"""

from __future__ import annotations

from app.logger import _redact


def test_redacts_top_level_secret_keys():
    out = _redact(
        {
            "ANTHROPIC_API_KEY": "sk-secret",
            "user_token": "abc",
            "db_PASSWORD": "p",
            "session_secret": "s",
            "normal": "ok",
        }
    )
    assert out["ANTHROPIC_API_KEY"] == "***REDACTED***"
    assert out["user_token"] == "***REDACTED***"
    assert out["db_PASSWORD"] == "***REDACTED***"
    assert out["session_secret"] == "***REDACTED***"
    assert out["normal"] == "ok"


def test_redacts_nested_and_lists():
    out = _redact({"a": {"X_SECRET": "s"}, "b": [{"y_token": "t"}, {"ok": 1}]})
    assert out["a"]["X_SECRET"] == "***REDACTED***"
    assert out["b"][0]["y_token"] == "***REDACTED***"
    assert out["b"][1]["ok"] == 1


def test_non_dict_values_pass_through():
    assert _redact("plain") == "plain"
    assert _redact(42) == 42
