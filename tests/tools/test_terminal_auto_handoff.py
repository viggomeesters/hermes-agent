import json

import pytest

from tools import process_registry as process_mod
from tools import terminal_tool as terminal_mod
from tools.process_registry import ProcessRegistry


@pytest.fixture
def isolated_registry(monkeypatch, tmp_path):
    registry = ProcessRegistry()
    monkeypatch.setattr(process_mod, "process_registry", registry)
    monkeypatch.setattr(process_mod, "CHECKPOINT_PATH", tmp_path / "processes.json")
    return registry


def _gateway_delivery(monkeypatch):
    from gateway import session_context

    values = {
        "HERMES_SESSION_PLATFORM": "telegram",
        "HERMES_SESSION_CHAT_ID": "chat-test",
        "HERMES_SESSION_THREAD_ID": "thread-test",
        "HERMES_SESSION_USER_ID": "user-test",
        "HERMES_SESSION_USER_NAME": "Test User",
        "HERMES_SESSION_MESSAGE_ID": "message-test",
    }
    monkeypatch.setattr(session_context, "async_delivery_supported", lambda: True)
    monkeypatch.setattr(session_context, "get_session_env", lambda key, default="": values.get(key, default))


def test_eligible_local_command_hands_off_without_killing_process(
    monkeypatch, tmp_path, isolated_registry
):
    _gateway_delivery(monkeypatch)
    monkeypatch.setattr(terminal_mod, "FOREGROUND_HANDOFF_BUDGET", 0.05)
    monkeypatch.setenv("TERMINAL_ENV", "local")

    result = json.loads(
        terminal_mod.terminal_tool(
            command="python3 -c 'import time; time.sleep(0.2); print(\"done\")'",
            timeout=2,
            task_id="auto-handoff-test",
            session_id="auto-handoff-test",
            workdir=str(tmp_path),
        )
    )

    assert result["status"] == "running"
    assert result["handoff"] is True
    assert result["notify_on_complete"] is True
    assert result["cwd"] == str(tmp_path)
    assert result["phase"] == "running"
    assert result["pid"]

    checkpoint = json.loads((tmp_path / "processes.json").read_text(encoding="utf-8"))
    persisted = next(item for item in checkpoint if item["session_id"] == result["session_id"])
    assert persisted["notify_on_complete"] is True
    assert persisted["watcher_platform"] == "telegram"
    assert persisted["host_start_time"]

    completed = isolated_registry.wait(result["session_id"], timeout=2)
    assert completed["status"] == "exited"
    assert completed["exit_code"] == 0
    assert "done" in completed["output"]


def test_quick_eligible_command_keeps_foreground_result_shape(
    monkeypatch, tmp_path, isolated_registry
):
    _gateway_delivery(monkeypatch)
    monkeypatch.setattr(terminal_mod, "FOREGROUND_HANDOFF_BUDGET", 1.0)
    monkeypatch.setenv("TERMINAL_ENV", "local")

    result = json.loads(
        terminal_mod.terminal_tool(
            command="printf quick",
            timeout=2,
            task_id="auto-handoff-quick-test",
            workdir=str(tmp_path),
        )
    )

    assert result["exit_code"] == 0
    assert result["output"] == "quick"
    assert "handoff" not in result


def test_interrupt_before_budget_kills_instead_of_silently_handing_off(
    monkeypatch, tmp_path, isolated_registry
):
    _gateway_delivery(monkeypatch)
    monkeypatch.setattr(terminal_mod, "FOREGROUND_HANDOFF_BUDGET", 1.0)
    monkeypatch.setattr(
        isolated_registry,
        "wait",
        lambda session_id, timeout=None: {
            "status": "interrupted",
            "output": "",
        },
    )
    monkeypatch.setenv("TERMINAL_ENV", "local")

    result = json.loads(
        terminal_mod.terminal_tool(
            command="sleep 5",
            timeout=2,
            task_id="auto-handoff-interrupt-test",
            workdir=str(tmp_path),
        )
    )

    assert result["status"] == "interrupted"
    assert result["exit_code"] == 130
    assert "handoff" not in result


def test_interactive_or_stateful_commands_are_not_eligible_for_handoff():
    assert terminal_mod._foreground_handoff_eligible(
        command="sleep 300",
        env_type="local",
        pty=True,
        approved_run=False,
        timeout=300,
        async_delivery=True,
        budget=120,
    ) is False
    assert terminal_mod._foreground_handoff_eligible(
        command="cd /tmp",
        env_type="local",
        pty=False,
        approved_run=False,
        timeout=300,
        async_delivery=True,
        budget=120,
    ) is False
    assert terminal_mod._foreground_handoff_eligible(
        command="rm -rf build && make all",
        env_type="local",
        pty=False,
        approved_run=True,
        timeout=300,
        async_delivery=True,
        budget=120,
    ) is False
