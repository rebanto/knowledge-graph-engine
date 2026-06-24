"""Regression tests for LLM rate-limit handling.

The reported failure mode: asking a question right after adding sources returned
an HTTP 500 because a transient per-minute Gemini 429 (RESOURCE_EXHAUSTED)
propagated out of the router/synthesizer. _call_sync must instead retry a
per-minute 429 with backoff, while still raising DailyQuotaExhausted for the
per-day quota (which a retry cannot fix).
"""
import pytest
from google.genai.errors import ClientError

import backend.core.llm_client as m


def _client_error(message: str) -> ClientError:
    return ClientError(
        429,
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": message}},
        None,
    )


class _FakeResp:
    def __init__(self, text="{}"):
        self.text = text


def _install_fake(monkeypatch, generate_fn):
    class FakeModels:
        def generate_content(self, model=None, contents=None, config=None):
            return generate_fn()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(m, "get_client", lambda: FakeClient())
    monkeypatch.setattr(m.time, "sleep", lambda s: None)            # no real waiting
    monkeypatch.setattr(m.gemini_breaker, "call", lambda fn: fn())  # breaker closed


def test_is_rate_limit_error_classifies():
    assert m._is_rate_limit_error(_client_error("retry in 9s")) is True
    assert m._is_rate_limit_error(ClientError(400, {"error": {"message": "bad"}}, None)) is False


def test_backoff_prefers_server_hint():
    # "retry in 3s" → ~3s (plus jitter), capped by _RATE_LIMIT_MAX_BACKOFF
    delay = m._rate_limit_backoff(_client_error("Please retry in 3s"), attempt=0)
    assert 3.0 <= delay <= m._RATE_LIMIT_MAX_BACKOFF + 1


def test_call_sync_retries_transient_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def gen():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _client_error("retry in 1s")
        return _FakeResp('{"ok": true}')

    _install_fake(monkeypatch, gen)
    result = m._call_sync("prompt", json_mode=True)
    assert result.text == '{"ok": true}'
    assert calls["n"] == 2  # first 429 was retried, second call succeeded


def test_call_sync_perday_raises_quota_without_retry(monkeypatch):
    calls = {"n": 0}

    def gen():
        calls["n"] += 1
        raise _client_error("Quota exceeded for ... PerDay limit")

    _install_fake(monkeypatch, gen)
    with pytest.raises(m.DailyQuotaExhausted):
        m._call_sync("prompt", json_mode=False)
    assert calls["n"] == 1  # per-day quota is not retried


def test_call_sync_raises_after_exhausting_429_retries(monkeypatch):
    def gen():
        raise _client_error("retry in 0.1s")

    _install_fake(monkeypatch, gen)
    with pytest.raises(ClientError):
        m._call_sync("prompt", json_mode=False, retries=1)
