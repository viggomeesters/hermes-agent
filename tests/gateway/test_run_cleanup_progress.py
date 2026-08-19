"""Tests for opt-in cleanup of temporary progress bubbles.

When ``display.platforms.<plat>.cleanup_progress: true`` is set for a
platform whose adapter supports message deletion (e.g. Telegram), the
tool-progress bubble, "⏳ Working — N min" heartbeats, and status-callback
messages sent during a run are deleted after the final response is
delivered.

Failed runs skip cleanup so the bubbles remain as breadcrumbs.
Adapters without ``delete_message`` silently no-op.
"""

import asyncio
import importlib
import inspect as _inspect
import logging
import sys
import time
import types
from types import SimpleNamespace

import pytest

from gateway.config import Platform, PlatformConfig


async def _fire_post_delivery_cb(cb):
    """Invoke a popped post-delivery callback, awaiting if it's async.

    Chained registrations return an async wrapper; single registrations
    return the raw sync callable. Either way, await any awaitable result.
    """
    result = cb()
    if _inspect.isawaitable(result):
        await result
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.session import SessionSource


# ---------------------------------------------------------------------------
# Test fakes — mirror those in test_run_progress_topics.py but add a
# delete_message implementation that records ids instead of hitting a bot.
# ---------------------------------------------------------------------------


class CleanupCaptureAdapter(BasePlatformAdapter):
    """Adapter that records every delete_message call for inspection."""

    _next_mid = 100

    def __init__(self, platform=Platform.TELEGRAM):
        super().__init__(PlatformConfig(enabled=True, token="***"), platform)
        self.sent = []
        self.edits = []
        self.deleted = []

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    def _mint_id(self) -> str:
        CleanupCaptureAdapter._next_mid += 1
        return str(CleanupCaptureAdapter._next_mid)

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        mid = self._mint_id()
        self.sent.append(
            {
                "chat_id": chat_id,
                "content": content,
                "message_id": mid,
                "metadata": metadata,
                "at": time.monotonic(),
            }
        )
        return SendResult(success=True, message_id=mid)

    async def edit_message(self, chat_id, message_id, content) -> SendResult:
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "content": content,
                "at": time.monotonic(),
            }
        )
        return SendResult(success=True, message_id=message_id)

    async def delete_message(self, chat_id, message_id) -> bool:
        self.deleted.append({"chat_id": chat_id, "message_id": str(message_id)})
        return True

    async def send_typing(self, chat_id, metadata=None) -> None:
        return None

    async def stop_typing(self, chat_id) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}


class NoDeleteAdapter(CleanupCaptureAdapter):
    """Adapter that inherits the base no-op delete_message (used to prove
    the cleanup path skips adapters without deletion support)."""

    async def delete_message(self, chat_id, message_id) -> bool:  # type: ignore[override]
        # Pretend to be an adapter whose platform doesn't support deletion:
        # match the base class behavior exactly. gateway/run.py checks
        # ``type(adapter).delete_message is BasePlatformAdapter.delete_message``
        # to detect this, so we re-assign at class body level below.
        raise AssertionError("should not be called — cleanup must skip this adapter")


# Re-bind so the class's delete_message identity equals the base's.
NoDeleteAdapter.delete_message = BasePlatformAdapter.delete_message


class ProgressAgent:
    """Emits two tool-progress events and returns a normal final response."""

    def __init__(self, **kwargs):
        self.tool_progress_callback = kwargs.get("tool_progress_callback")
        self.tools = []

    def run_conversation(self, message, conversation_history=None, task_id=None):
        cb = self.tool_progress_callback
        if cb is not None:
            cb("tool.started", "terminal", "pwd", {})
            time.sleep(0.2)
            cb("tool.started", "terminal", "ls", {})
            time.sleep(0.2)
        return {"final_response": "done", "messages": [], "api_calls": 1}


class FailingAgent:
    def __init__(self, **kwargs):
        self.tool_progress_callback = kwargs.get("tool_progress_callback")
        self.tools = []

    def run_conversation(self, message, conversation_history=None, task_id=None):
        cb = self.tool_progress_callback
        if cb is not None:
            cb("tool.started", "terminal", "pwd", {})
            time.sleep(0.2)
        # Empty final_response + failed=True is the shape the gateway
        # actually returns on provider errors (see gateway/run.py where
        # failed keys are only propagated when final_response is empty).
        return {
            "final_response": "",
            "messages": [],
            "api_calls": 1,
            "failed": True,
            "error": "simulated provider failure",
        }


class SlowOperationCardAgent:
    """Stays alive long enough for a card and emits real phase changes."""

    def __init__(self, **kwargs):
        self.tool_progress_callback = kwargs.get("tool_progress_callback")
        self.tools = []
        self.current_tool = None
        self.api_call_count = 0

    def get_activity_summary(self):
        return {
            "current_tool": self.current_tool,
            "api_call_count": self.api_call_count,
            "seconds_since_activity": 0.0,
        }

    def run_conversation(self, message, conversation_history=None, task_id=None):
        time.sleep(0.15)
        self.current_tool = "read_file"
        if self.tool_progress_callback is not None:
            self.tool_progress_callback("tool.started", "read_file", "config.yaml", {})
        time.sleep(0.10)
        self.current_tool = "patch"
        if self.tool_progress_callback is not None:
            self.tool_progress_callback("tool.started", "patch", "gateway/run.py", {})
        time.sleep(0.10)
        self.api_call_count = 1
        return {"final_response": "done", "messages": [], "api_calls": 1}


class SlowNoPhaseAgent:
    """Long enough for one card, without tool callbacks."""

    def __init__(self, **kwargs):
        self.tools = []
        self.task_id = "task-no-phase"

    def run_conversation(self, message, conversation_history=None, task_id=None):
        time.sleep(0.14)
        return {"final_response": "done", "messages": [], "api_calls": 0}

    def get_activity_summary(self):
        return {"description": "working", "api_call_count": 0}


class RacingOperationCardAgent(SlowOperationCardAgent):
    """Emit a phase change immediately before the periodic heartbeat."""

    def run_conversation(self, message, conversation_history=None, task_id=None):
        time.sleep(0.11)
        self.current_tool = "read_file"
        if self.tool_progress_callback is not None:
            self.tool_progress_callback("tool.started", "read_file", "config.yaml", {})
        time.sleep(0.20)
        return {"final_response": "done", "messages": [], "api_calls": 1}


class CoalescingOperationCardAgent(SlowOperationCardAgent):
    """Emit two phases while the first edit is waiting on the rate limit."""

    def run_conversation(self, message, conversation_history=None, task_id=None):
        time.sleep(0.07)
        self.current_tool = "read_file"
        if self.tool_progress_callback is not None:
            self.tool_progress_callback("tool.started", "read_file", "config.yaml", {})
        time.sleep(0.005)
        self.current_tool = "patch"
        if self.tool_progress_callback is not None:
            self.tool_progress_callback("tool.started", "patch", "gateway/run.py", {})
        time.sleep(0.35)
        return {"final_response": "done", "messages": [], "api_calls": 1}


def _make_runner(adapter):
    gateway_run = importlib.import_module("gateway.run")
    GatewayRunner = gateway_run.GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner.adapters = {adapter.platform: adapter}
    runner._voice_mode = {}
    runner._prefill_messages = []
    runner._ephemeral_system_prompt = ""
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._session_db = None
    runner._running_agents = {}
    runner._session_run_generation = {}
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(
        thread_sessions_per_user=False,
        group_sessions_per_user=False,
        stt_enabled=False,
    )
    return runner


def _install_fakes(
    monkeypatch,
    agent_cls,
    *,
    cleanup_on: bool,
    cleanup_platform: Platform = Platform.TELEGRAM,
    platform_display: dict | None = None,
):
    """Wire up the module stubs every _run_agent test needs."""
    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "all")

    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = agent_cls
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    import tools.terminal_tool  # noqa: F401 — register tool emoji

    gateway_run = importlib.import_module("gateway.run")
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "fake"})

    # Wire the per-platform cleanup_progress flag via the config loader the
    # gateway actually reads (``_load_gateway_config`` returns user config).
    display_cfg = dict(platform_display or {})
    if cleanup_on:
        display_cfg["cleanup_progress"] = True
    cfg = {
        "display": {
            "platforms": {
                cleanup_platform.value: display_cfg,
            }
        }
    } if display_cfg else {}
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: cfg)
    return gateway_run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messaging_agent_forwards_checkpoint_config(monkeypatch, tmp_path):
    """Writable gateway agents must receive the configured checkpoint limits."""
    captured = {}

    class CheckpointCaptureAgent(ProgressAgent):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(
        monkeypatch, CheckpointCaptureAgent, cleanup_on=False,
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {
            "checkpoints": {
                "enabled": True,
                "max_snapshots": 9,
                "max_total_size_mb": 444,
                "max_file_size_mb": 6,
            }
        },
    )

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="-1001")
    result = await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=source,
        session_id="sess-checkpoints",
        session_key="agent:main:telegram:group:-1001",
    )

    assert result["final_response"] == "done"
    assert captured["checkpoints_enabled"] is True
    assert captured["checkpoint_max_snapshots"] == 9
    assert captured["checkpoint_max_total_size_mb"] == 444
    assert captured["checkpoint_max_file_size_mb"] == 6


@pytest.mark.asyncio
async def test_cleanup_coexists_with_existing_callback(monkeypatch, tmp_path):
    """General and success-only callbacks coexist without clobbering."""
    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(monkeypatch, ProgressAgent, cleanup_on=True)
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="-1001")
    session_key = "agent:main:telegram:group:-1001"

    pre_existing_fired = []

    def _preexisting_callback() -> None:
        pre_existing_fired.append(True)

    # Pre-register a callback with the same generation the run will use
    # (run_generation=None in this test path — matches the default slot).
    adapter.register_post_delivery_callback(session_key, _preexisting_callback)

    result = await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=source,
        session_id="sess-1",
        session_key=session_key,
    )

    assert result["final_response"] == "done"
    general_cb = adapter.pop_post_delivery_callback(session_key)
    cleanup_cb = adapter.pop_post_delivery_callback(session_key, success_only=True)
    assert callable(general_cb)
    assert callable(cleanup_cb)
    await _fire_post_delivery_cb(general_cb)
    await _fire_post_delivery_cb(cleanup_cb)
    for _ in range(20):
        await asyncio.sleep(0.01)
        if adapter.deleted:
            break

    # Both effects land: the pre-existing callback fires AND the cleanup
    # deletes at least one progress bubble.
    assert pre_existing_fired == [True]
    assert len(adapter.deleted) >= 1


@pytest.mark.asyncio
async def test_operation_card_tracks_phase_changes_and_is_removed_after_final_delivery(
    monkeypatch, tmp_path, caplog
):
    """The single long-run card is live during work and disappears after success."""
    caplog.set_level(logging.INFO, logger="gateway.operation_card_controller")
    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(
        monkeypatch,
        SlowOperationCardAgent,
        cleanup_on=True,
        platform_display={
            "operation_cards": True,
            "long_running_notifications": True,
            "operation_card_phase_update_interval": 0.01,
            "tool_progress": False,
        },
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_AGENT_FIRST_NOTIFY_DELAY", "0.06")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")
    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "off")

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="-1001")
    session_key = "agent:main:telegram:group:-1001"
    result = await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=source,
        session_id="sess-operation-card",
        session_key=session_key,
    )

    assert result["final_response"] == "done"
    assert len(adapter.sent) == 1
    card_id = adapter.sent[0]["message_id"]
    edit_texts = [edit["content"] for edit in adapter.edits]
    assert any("Fase: read file" in text for text in edit_texts), adapter.edits
    assert any("Fase: patch" in text for text in edit_texts), adapter.edits

    cb = adapter.pop_post_delivery_callback(session_key, success_only=True)
    assert callable(cb)
    await _fire_post_delivery_cb(cb)
    for _ in range(20):
        await asyncio.sleep(0.01)
        if adapter.deleted:
            break

    assert {item["message_id"] for item in adapter.deleted} == {card_id}
    assert any(
        getattr(record, "operation_card_event", None) == "removed"
        and getattr(record, "operation_card_reason", None)
        == "final_delivery_succeeded"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_failed_operation_card_is_retained_with_structured_reason(
    monkeypatch,
    tmp_path,
    caplog,
):
    caplog.set_level(logging.INFO, logger="gateway.operation_card_controller")
    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(
        monkeypatch,
        FailingAgent,
        cleanup_on=True,
        platform_display={
            "operation_cards": True,
            "long_running_notifications": True,
            "operation_card_phase_update_interval": 0.01,
            "tool_progress": False,
        },
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_AGENT_FIRST_NOTIFY_DELAY", "0.06")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")

    result = await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="-1005"),
        session_id="sess-retained",
        session_key="agent:main:telegram:group:-1005",
    )

    assert result["failed"] is True
    assert adapter.sent
    assert adapter.deleted == []
    assert any(
        getattr(record, "operation_card_event", None) == "retained"
        and getattr(record, "operation_card_reason", None) == "agent_run_failed"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_operation_card_heartbeat_observes_progress_once(monkeypatch, tmp_path):
    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(
        monkeypatch,
        SlowNoPhaseAgent,
        cleanup_on=True,
        platform_display={
            "operation_cards": True,
            "long_running_notifications": True,
            "operation_card_phase_update_interval": 0.01,
            "tool_progress": False,
        },
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_AGENT_FIRST_NOTIFY_DELAY", "0.06")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")

    operation_card_module = importlib.import_module("gateway.operation_card")
    real_tracker = operation_card_module.ProgressTracker

    class CountingTracker(real_tracker):
        observations = 0

        def observe(self, snapshot):
            type(self).observations += 1
            return super().observe(snapshot)

    monkeypatch.setattr(operation_card_module, "ProgressTracker", CountingTracker)

    await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="-1002"),
        session_id="sess-single-observation",
        session_key="agent:main:telegram:group:-1002",
    )

    # Initial running card + terminal completed edit: one observation each.
    assert CountingTracker.observations == 2


@pytest.mark.asyncio
async def test_phase_and_heartbeat_edits_share_one_rate_limit(monkeypatch, tmp_path):
    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(
        monkeypatch,
        RacingOperationCardAgent,
        cleanup_on=True,
        platform_display={
            "operation_cards": True,
            "long_running_notifications": True,
            "operation_card_phase_update_interval": 0.08,
            "tool_progress": False,
        },
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_AGENT_FIRST_NOTIFY_DELAY", "0.06")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "0.12")
    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "off")

    await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="-1003"),
        session_id="sess-rate-limit",
        session_key="agent:main:telegram:group:-1003",
    )

    running_updates = [
        item
        for item in [*adapter.sent, *adapter.edits]
        if "Status: 🟢 actief" in item["content"]
    ]
    gaps = [
        current["at"] - previous["at"]
        for previous, current in zip(running_updates, running_updates[1:])
    ]
    assert len(gaps) >= 2, running_updates
    assert min(gaps) >= 0.07, gaps


@pytest.mark.asyncio
async def test_rapid_phase_events_coalesce_identical_rendered_edit(monkeypatch, tmp_path):
    adapter = CleanupCaptureAdapter()
    runner = _make_runner(adapter)
    gateway_run = _install_fakes(
        monkeypatch,
        CoalescingOperationCardAgent,
        cleanup_on=True,
        platform_display={
            "operation_cards": True,
            "long_running_notifications": True,
            "operation_card_phase_update_interval": 0.08,
            "tool_progress": False,
        },
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_AGENT_FIRST_NOTIFY_DELAY", "0.06")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")
    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "off")

    await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="-1004"),
        session_id="sess-coalesce",
        session_key="agent:main:telegram:group:-1004",
    )

    patch_running_edits = [
        edit
        for edit in adapter.edits
        if "Status: 🟢 actief" in edit["content"]
        and "Fase: patch" in edit["content"]
    ]
    assert len(patch_running_edits) == 1, adapter.edits
