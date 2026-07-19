from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _configure(monkeypatch, tmp_path: Path, *, limit: int = 3, timeout: float = 0.02):
    from agent import provider_concurrency as concurrency

    monkeypatch.setattr(concurrency, "_shared_root", lambda: tmp_path)
    monkeypatch.setattr(
        concurrency,
        "_load_provider_settings",
        lambda provider: concurrency.ProviderConcurrencySettings(
            max_concurrent_requests=limit,
            acquire_timeout_seconds=timeout,
            poll_interval_seconds=0.001,
        ),
    )
    return concurrency


def test_fourth_codex_request_waits_until_a_slot_is_released(monkeypatch, tmp_path):
    concurrency = _configure(monkeypatch, tmp_path)

    leases = [concurrency.acquire_provider_request("openai-codex") for _ in range(3)]
    with pytest.raises(concurrency.ProviderConcurrencyTimeout):
        concurrency.acquire_provider_request("openai-codex")

    leases[0].release()
    replacement = concurrency.acquire_provider_request("openai-codex")
    assert replacement.enabled

    replacement.release()
    for lease in leases[1:]:
        lease.release()


def test_context_manager_releases_slot_after_exception(monkeypatch, tmp_path):
    concurrency = _configure(monkeypatch, tmp_path, limit=1)

    with pytest.raises(RuntimeError):
        with concurrency.provider_request_slot("openai-codex"):
            raise RuntimeError("boom")

    with concurrency.provider_request_slot("openai-codex") as lease:
        assert lease.enabled


def test_dead_process_leases_are_pruned(monkeypatch, tmp_path):
    concurrency = _configure(monkeypatch, tmp_path, limit=1)
    state_path = tmp_path / "runtime" / "provider_requests.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "lease_id": "dead",
                        "provider": "openai-codex",
                        "pid": 999999999,
                        "process_start_time": 1.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    lease = concurrency.acquire_provider_request("openai-codex")
    assert lease.enabled
    snapshot = concurrency.provider_request_registry_snapshot()
    assert [entry["lease_id"] for entry in snapshot] == [lease.lease_id]
    lease.release()


def test_unconfigured_provider_is_a_noop(monkeypatch, tmp_path):
    from agent import provider_concurrency as concurrency

    monkeypatch.setattr(concurrency, "_shared_root", lambda: tmp_path)
    monkeypatch.setattr(concurrency, "_load_provider_settings", lambda provider: None)

    lease = concurrency.acquire_provider_request("another-provider")
    assert not lease.enabled
    assert not (tmp_path / "runtime" / "provider_requests.json").exists()


def test_named_profiles_resolve_to_one_shared_registry(monkeypatch, tmp_path):
    from agent import provider_concurrency as concurrency

    monkeypatch.setattr(concurrency, "get_default_hermes_root", lambda: tmp_path)
    assert concurrency._state_path() == tmp_path / "runtime" / "provider_requests.json"


def test_primary_codex_stream_holds_shared_slot(monkeypatch):
    from agent import codex_runtime
    from agent import provider_concurrency as concurrency

    calls = []

    @contextmanager
    def _slot(provider, *, purpose="primary"):
        calls.append(("enter", provider, purpose))
        try:
            yield SimpleNamespace(enabled=True)
        finally:
            calls.append(("exit", provider, purpose))

    monkeypatch.setattr(concurrency, "provider_request_slot", _slot)
    response = SimpleNamespace(output=[], status="completed")
    client = MagicMock()
    client.responses.create.return_value = response
    agent = SimpleNamespace(
        _interrupt_requested=False,
        _codex_streamed_text_parts=[],
        _fire_stream_delta=lambda text: None,
        _fire_reasoning_delta=lambda text: None,
        _touch_activity=lambda reason: None,
        _client_log_context=lambda: "test",
    )

    assert codex_runtime.run_codex_stream(agent, {}, client=client) is response
    assert calls == [
        ("enter", "openai-codex", "primary"),
        ("exit", "openai-codex", "primary"),
    ]


def test_auxiliary_codex_stream_holds_shared_slot(monkeypatch):
    from agent.auxiliary_client import _CodexCompletionsAdapter
    from agent import provider_concurrency as concurrency

    calls = []

    @contextmanager
    def _slot(provider, *, purpose="primary"):
        calls.append(("enter", provider, purpose))
        try:
            yield SimpleNamespace(enabled=True)
        finally:
            calls.append(("exit", provider, purpose))

    monkeypatch.setattr(concurrency, "provider_request_slot", _slot)
    message_item = SimpleNamespace(
        type="message",
        role="assistant",
        status="completed",
        content=[SimpleNamespace(type="output_text", text="hi")],
    )
    events = [
        SimpleNamespace(type="response.output_item.done", item=message_item),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", id="resp_test", usage=None),
        ),
    ]

    class _Stream:
        def __iter__(self):
            return iter(events)

        def close(self):
            pass

    client = MagicMock()
    client.responses.create.return_value = _Stream()
    adapter = _CodexCompletionsAdapter(client, "gpt-5.5")

    adapter.create(messages=[{"role": "user", "content": "hi"}])
    assert calls == [
        ("enter", "openai-codex", "auxiliary"),
        ("exit", "openai-codex", "auxiliary"),
    ]


def test_default_config_documents_provider_concurrency_section():
    from hermes_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["provider_concurrency"] == {}
