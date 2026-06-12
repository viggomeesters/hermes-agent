import time
from unittest.mock import MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource, build_session_key
from gateway.run import GatewayRunner


class _PendingAdapter:
    def __init__(self):
        self._pending_messages = {}


def _make_runner():
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")})
    runner.adapters = {Platform.TELEGRAM: _PendingAdapter()}
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._queued_events = {}
    runner._pending_approvals = {}
    runner._voice_mode = {}
    runner._busy_input_mode = "queue"
    runner._busy_text_mode = "queue"
    runner._draining = False
    runner._restart_requested = False
    setattr(runner, "session_store", None)
    runner._is_user_authorized = lambda _source: True
    return runner


def _photo_event(source, text, path):
    return MessageEvent(
        text=text,
        message_type=MessageType.PHOTO,
        source=source,
        media_urls=[path],
        media_types=["image/jpeg"],
    )


@pytest.mark.asyncio
async def test_handle_message_does_not_priority_interrupt_photo_followup():
    runner = _make_runner()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    session_key = build_session_key(source)
    running_agent = MagicMock()
    runner._running_agents[session_key] = running_agent

    event = _photo_event(source, "caption", "/tmp/photo-a.jpg")

    result = await runner._handle_message(event)

    assert result is None
    running_agent.interrupt.assert_not_called()
    assert runner.adapters[Platform.TELEGRAM]._pending_messages[session_key] is event


@pytest.mark.asyncio
async def test_priority_photo_followups_stay_fifo_in_queue_mode():
    runner = _make_runner()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    session_key = build_session_key(source)
    runner._running_agents[session_key] = MagicMock()

    first = _photo_event(source, "Nieuwe taak: one", "/tmp/photo-one.jpg")
    second = _photo_event(source, "Nieuwe taak: two", "/tmp/photo-two.jpg")

    assert await runner._handle_message(first) is None
    assert await runner._handle_message(second) is None

    adapter = runner.adapters[Platform.TELEGRAM]
    assert adapter._pending_messages[session_key] is first
    assert adapter._pending_messages[session_key].media_urls == ["/tmp/photo-one.jpg"]
    assert runner._queued_events[session_key] == [second]


@pytest.mark.asyncio
async def test_priority_draining_reports_queue_full_when_enqueue_rejected():
    runner = _make_runner()
    setattr(runner, "_BUSY_QUEUE_MAX_PENDING", 1)
    runner._draining = True
    runner._restart_requested = True
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    session_key = build_session_key(source)
    runner._running_agents[session_key] = MagicMock()

    first = MessageEvent(text="first", message_type=MessageType.TEXT, source=source)
    second = MessageEvent(text="second", message_type=MessageType.TEXT, source=source)

    first_result = await runner._handle_message(first)
    assert isinstance(first_result, str)
    assert "queued for the next turn" in first_result
    result = await runner._handle_message(second)

    assert isinstance(result, str)
    assert "Queue full" in result
    assert "could not queue" in result


@pytest.mark.asyncio
async def test_priority_telegram_grace_reports_queue_full_when_enqueue_rejected():
    runner = _make_runner()
    setattr(runner, "_BUSY_QUEUE_MAX_PENDING", 1)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm", user_id="u1")
    session_key = build_session_key(source)
    running_agent = MagicMock()
    running_agent.get_activity_summary.return_value = {"seconds_since_activity": 0.0}
    runner._running_agents[session_key] = running_agent
    runner._running_agents_ts[session_key] = time.time()

    first = MessageEvent(text="first", message_type=MessageType.TEXT, source=source)
    second = MessageEvent(text="second", message_type=MessageType.TEXT, source=source)

    assert await runner._handle_message(first) is None
    result = await runner._handle_message(second)

    assert isinstance(result, str)
    assert "Queue full" in result
    assert "could not queue" in result
    adapter = runner.adapters[Platform.TELEGRAM]
    assert adapter._pending_messages[session_key] is first
    assert session_key not in runner._queued_events
