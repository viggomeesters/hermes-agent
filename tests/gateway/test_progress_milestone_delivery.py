from unittest.mock import AsyncMock
from datetime import datetime

import pytest

from gateway.run import (
    _build_long_running_heartbeat,
    _format_gateway_status_copy,
    _send_long_running_heartbeat_coro,
    _send_or_update_status_coro,
    _status_is_cleanup_eligible,
)


@pytest.mark.asyncio
async def test_milestone_is_a_durable_separate_message():
    adapter = type("Adapter", (), {})()
    adapter.send = AsyncMock(return_value=type("Result", (), {"success": True})())
    adapter.send_or_update_status = AsyncMock()

    await _send_or_update_status_coro(
        adapter,
        "chat-1",
        "milestone",
        "✅ TASK-1 afgerond en vastgelegd.",
        {"thread_id": "topic-7"},
    )

    adapter.send.assert_awaited_once_with(
        "chat-1",
        "✅ TASK-1 afgerond en vastgelegd.",
        metadata={"thread_id": "topic-7"},
    )
    adapter.send_or_update_status.assert_not_awaited()
    assert _status_is_cleanup_eligible("milestone") is False


def test_default_milestone_copy_is_generic_core_text():
    assert _format_gateway_status_copy(
        {}, "telegram", "milestone", "TASK-1"
    ) == "✅ TASK-1 completed and recorded."


@pytest.mark.asyncio
async def test_heartbeat_is_a_durable_separate_message():
    adapter = type("Adapter", (), {})()
    adapter.send = AsyncMock(return_value=type("Result", (), {"success": True})())
    adapter.send_or_update_status = AsyncMock(
        return_value=type("Result", (), {"success": True})()
    )

    await _send_or_update_status_coro(
        adapter,
        "chat-1",
        "heartbeat",
        "⏳ Working — 10 min",
        {"thread_id": "topic-7"},
        append_only_heartbeat=True,
    )

    adapter.send.assert_awaited_once_with(
        "chat-1",
        "⏳ Working — 10 min",
        metadata={"thread_id": "topic-7"},
    )
    adapter.send_or_update_status.assert_not_awaited()
    assert _status_is_cleanup_eligible(
        "heartbeat", append_only_heartbeat=True
    ) is False


@pytest.mark.asyncio
async def test_non_telegram_heartbeat_keeps_edit_in_place_rail():
    adapter = type("Adapter", (), {})()
    adapter.send = AsyncMock()
    adapter.send_or_update_status = AsyncMock(
        return_value=type("Result", (), {"success": True})()
    )

    await _send_or_update_status_coro(
        adapter,
        "chat-1",
        "heartbeat",
        "⏳ Working — 10 min",
        {"thread_id": "thread-7"},
        append_only_heartbeat=False,
    )

    adapter.send_or_update_status.assert_awaited_once_with(
        "chat-1",
        "heartbeat",
        "⏳ Working — 10 min",
        metadata={"thread_id": "thread-7"},
    )
    adapter.send.assert_not_awaited()
    assert _status_is_cleanup_eligible(
        "heartbeat", append_only_heartbeat=False
    ) is True


@pytest.mark.asyncio
async def test_long_running_telegram_heartbeat_always_sends_new_message():
    adapter = type("Adapter", (), {})()
    adapter.send = AsyncMock(
        return_value=type("Result", (), {"success": True, "message_id": "new-8"})()
    )
    adapter.edit_message = AsyncMock()

    result, message_id = await _send_long_running_heartbeat_coro(
        adapter,
        "chat-1",
        "⏳ Working — 30 min",
        {"thread_id": "topic-7"},
        append_only=True,
        message_id="old-7",
    )

    assert result.success is True
    assert message_id is None
    adapter.send.assert_awaited_once_with(
        "chat-1",
        "⏳ Working — 30 min",
        metadata={"thread_id": "topic-7"},
    )
    adapter.edit_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_running_non_telegram_heartbeat_edits_existing_message():
    adapter = type("Adapter", (), {})()
    adapter.send = AsyncMock()
    adapter.edit_message = AsyncMock(
        return_value=type("Result", (), {"success": True, "message_id": "old-7"})()
    )

    result, message_id = await _send_long_running_heartbeat_coro(
        adapter,
        "chat-1",
        "⏳ Working — 30 min",
        {"thread_id": "thread-7"},
        append_only=False,
        message_id="old-7",
    )

    assert result.success is True
    assert message_id == "old-7"
    adapter.edit_message.assert_awaited_once_with(
        "chat-1", "old-7", "⏳ Working — 30 min"
    )
    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_operation_card_failed_edit_falls_back_to_one_new_card():
    adapter = type("Adapter", (), {})()
    adapter.edit_message = AsyncMock(
        return_value=type("Result", (), {"success": False, "message_id": None})()
    )
    adapter.send = AsyncMock(
        return_value=type("Result", (), {"success": True, "message_id": "card-2"})()
    )

    result, message_id = await _send_long_running_heartbeat_coro(
        adapter,
        "chat-1",
        "⚙️ Operatie\nStatus: 🟢 actief",
        {"thread_id": "topic-7"},
        append_only=False,
        message_id="card-1",
    )

    assert result.success is True
    assert message_id == "card-2"
    adapter.edit_message.assert_awaited_once_with(
        "chat-1", "card-1", "⚙️ Operatie\nStatus: 🟢 actief"
    )
    adapter.send.assert_awaited_once_with(
        "chat-1",
        "⚙️ Operatie\nStatus: 🟢 actief",
        metadata={"thread_id": "topic-7"},
    )


@pytest.mark.asyncio
async def test_operation_card_updates_without_deleting_append_only_breadcrumb():
    adapter = type("Adapter", (), {})()
    adapter.send = AsyncMock(
        side_effect=[
            type("Result", (), {"success": True, "message_id": "card-1"})(),
            type("Result", (), {"success": True, "message_id": "crumb-1"})(),
        ]
    )
    adapter.edit_message = AsyncMock(
        return_value=type("Result", (), {"success": True, "message_id": "card-1"})()
    )

    _, card_id = await _send_long_running_heartbeat_coro(
        adapter,
        "chat-1",
        "⚙️ Operatie\nVoortgang: 1/2",
        {},
        append_only=False,
    )
    await adapter.send("chat-1", "🔧 terminal: batch 1")
    _, updated_id = await _send_long_running_heartbeat_coro(
        adapter,
        "chat-1",
        "⚙️ Operatie\nVoortgang: 2/2",
        {},
        append_only=False,
        message_id=card_id,
    )

    assert updated_id == "card-1"
    assert adapter.send.await_count == 2
    adapter.edit_message.assert_awaited_once_with(
        "chat-1", "card-1", "⚙️ Operatie\nVoortgang: 2/2"
    )


def test_heartbeat_reports_last_real_activity_and_current_action():
    agent = type("Agent", (), {})()
    agent.get_activity_summary = lambda: {
        "api_call_count": 7,
        "max_iterations": 90,
        "current_tool": "terminal",
        "last_activity_desc": "executing tool: terminal",
        "seconds_since_activity": 125.0,
    }

    text = _build_long_running_heartbeat(
        agent,
        elapsed_mins=22,
        want_iteration_detail=False,
        updated_at=datetime(2026, 7, 25, 7, 21),
    )

    assert text == (
        "⏳ Working — 22 min — updated 07:21 — "
        "terminal, last activity 2 min ago"
    )


def test_heartbeat_marks_missing_activity_as_possible_stall():
    agent = type("Agent", (), {})()
    agent.get_activity_summary = lambda: {
        "api_call_count": 12,
        "max_iterations": 90,
        "current_tool": None,
        "last_activity_desc": "waiting for model",
        "seconds_since_activity": 965.0,
    }

    text = _build_long_running_heartbeat(
        agent,
        elapsed_mins=41,
        want_iteration_detail=True,
        updated_at=datetime(2026, 7, 25, 7, 31),
    )

    assert text == (
        "⚠️ Possibly stalled — 41 min — updated 07:31 — iteration 12/90, "
        "waiting for model, no activity for 16 min"
    )


def test_heartbeat_degrades_cleanly_without_agent_summary():
    assert _build_long_running_heartbeat(
        None,
        elapsed_mins=10,
        want_iteration_detail=False,
        updated_at=datetime(2026, 7, 25, 7, 41),
    ) == "⏳ Working — 10 min — updated 07:41"


def test_heartbeat_formats_long_elapsed_time_as_hours_not_hundreds_of_minutes():
    assert _build_long_running_heartbeat(
        None,
        elapsed_mins=640,
        want_iteration_detail=False,
        updated_at=datetime(2026, 7, 25, 7, 51),
    ) == "⏳ Working — 10h 40m — updated 07:51"
