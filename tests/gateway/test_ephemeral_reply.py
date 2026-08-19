"""Tests for EphemeralReply — system-notice auto-delete in gateway adapters.

Slash-command handlers in ``gateway/run.py`` can return an
``EphemeralReply`` wrapper to request auto-deletion of the reply message
after a TTL.  The base adapter unwraps the sentinel before sending and
schedules a detached delete task when the platform supports
``delete_message``.

Covered:

1. ``_unwrap_ephemeral`` returns text + ttl for EphemeralReply, and
   passes plain strings through unchanged.
2. TTL is zeroed on platforms that don't override ``delete_message``
   (silent degrade — message stays in place).
3. TTL is honored on platforms that DO override ``delete_message``.
4. ``_schedule_ephemeral_delete`` invokes ``delete_message`` after the
   configured delay with the correct chat_id / message_id.
5. ``_process_message_background`` sends the unwrapped text (not the
   sentinel object) and schedules deletion when appropriate.
6. The two busy-session bypass paths also unwrap + schedule.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    EphemeralReply,
    MessageEvent,
    MessageType,
    SendResult,
)
from gateway.session import SessionSource


class _NoDeleteAdapter(BasePlatformAdapter):
    """Adapter that does NOT override delete_message (silent degrade)."""

    async def connect(self, *, is_reconnect: bool = False):
        pass

    async def disconnect(self):
        pass

    async def send(self, chat_id, content="", **kwargs):
        return SendResult(success=True, message_id="m-1")

    async def get_chat_info(self, chat_id):
        return {}


class _DeleteCapableAdapter(BasePlatformAdapter):
    """Adapter that overrides delete_message (TTL honored)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.deleted: list[tuple[str, str]] = []

    async def connect(self, *, is_reconnect: bool = False):
        pass

    async def disconnect(self):
        pass

    async def send(self, chat_id, content="", **kwargs):
        return SendResult(success=True, message_id="m-2")

    async def get_chat_info(self, chat_id):
        return {}

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        self.deleted.append((chat_id, message_id))
        return True


class _LegacyCallbackAdapter(_DeleteCapableAdapter):
    """Old callback overrides without the new success_only keyword."""

    def register_post_delivery_callback(
        self,
        session_key,
        callback,
        *,
        generation=None,
    ):
        return super().register_post_delivery_callback(
            session_key,
            callback,
            generation=generation,
        )

    def pop_post_delivery_callback(self, session_key, *, generation=None):
        return super().pop_post_delivery_callback(
            session_key,
            generation=generation,
        )


def _no_delete_adapter():
    return _NoDeleteAdapter(
        PlatformConfig(enabled=True, token="t"), Platform.TELEGRAM
    )


def _delete_adapter():
    return _DeleteCapableAdapter(
        PlatformConfig(enabled=True, token="t"), Platform.TELEGRAM
    )


def _make_event(text="/stop", chat_id="42"):
    return MessageEvent(
        text=text,
        message_id="msg-1",
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id=chat_id,
            user_id="u-1",
        ),
        message_type=MessageType.TEXT,
    )


# ---------------------------------------------------------------------------
# _unwrap_ephemeral
# ---------------------------------------------------------------------------


def test_unwrap_ephemeral_default_ttl_zero_disables():
    """Config default of 0 (the shipped default) means the feature is off."""
    adapter = _delete_adapter()
    with patch.object(adapter, "_get_ephemeral_system_ttl_default", return_value=0):
        text, ttl = adapter._unwrap_ephemeral(EphemeralReply("bye"))
    assert text == "bye"
    assert ttl == 0


def test_unwrap_ephemeral_handles_unreadable_config():
    adapter = _delete_adapter()
    with patch.object(
        adapter,
        "_get_ephemeral_system_ttl_default",
        side_effect=RuntimeError("boom"),
    ):
        text, ttl = adapter._unwrap_ephemeral(EphemeralReply("bye"))
    # Fall back to 0 rather than crashing the handler pipeline.
    assert text == "bye"
    assert ttl == 0


# ---------------------------------------------------------------------------
# _schedule_ephemeral_delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_ephemeral_delete_calls_delete_after_ttl():
    adapter = _delete_adapter()
    # Use a very short TTL to keep the test fast — the implementation
    # floors sleeps at 1s via ``max(1, int(ttl_seconds))``.  Patch asyncio.sleep
    # inside the module under test; the test body uses the real one for
    # scheduler pumping.
    import gateway.platforms.base as base_module

    sleeps: list[float] = []
    _real_sleep = base_module.asyncio.sleep

    async def _fake_sleep(duration):
        sleeps.append(duration)
        # Yield control so the rest of the task body can run.
        await _real_sleep(0)

    with patch.object(base_module.asyncio, "sleep", _fake_sleep):
        adapter._schedule_ephemeral_delete(
            chat_id="42", message_id="m-2", ttl_seconds=5
        )
        # Let the spawned task run.
        for _ in range(5):
            await _real_sleep(0)

    # Only the ttl sleep shows up — the test pump uses the real sleep.
    assert 5 in sleeps
    assert adapter.deleted == [("42", "m-2")]


# ---------------------------------------------------------------------------
# _process_message_background unwraps EphemeralReply before send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_message_unwraps_ephemeral_before_send():
    """The adapter must send the wrapper's .text, never the wrapper object."""
    adapter = _delete_adapter()
    adapter._send_with_retry = AsyncMock(
        return_value=SendResult(success=True, message_id="sent-1")
    )

    async def _handler(evt):
        return EphemeralReply("⚡ Stopped.", ttl_seconds=5)

    adapter.set_message_handler(_handler)

    sleeps: list[float] = []

    async def _fake_sleep(duration):
        sleeps.append(duration)

    event = _make_event()
    session_key = "agent:main:telegram:private:42"
    with patch("gateway.platforms.base.asyncio.sleep", _fake_sleep), patch.object(
        adapter, "_keep_typing", new=AsyncMock()
    ):
        await adapter._process_message_background(event, session_key)
        # Pump until the detached delete task completes.
        for _ in range(10):
            await asyncio.sleep(0)

    # Sent text is the unwrapped string, NOT repr(EphemeralReply(...))
    adapter._send_with_retry.assert_called_once()
    sent_text = adapter._send_with_retry.call_args.kwargs["content"]
    assert sent_text == "⚡ Stopped."
    # Auto-delete scheduled using the returned message_id
    assert ("42", "sent-1") in adapter.deleted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("send_success", "expected"),
    ((True, ["cleanup"]), (False, [])),
)
async def test_success_only_post_delivery_callback_requires_successful_send(
    send_success,
    expected,
):
    adapter = _delete_adapter()
    adapter._send_with_retry = AsyncMock(
        return_value=SendResult(
            success=send_success,
            message_id="sent-1" if send_success else None,
            error=None if send_success else "network down",
        )
    )

    async def _handler(evt):
        return "final response"

    adapter.set_message_handler(_handler)
    fired = []
    attempt_callbacks = []
    session_key = "agent:main:telegram:private:42"
    adapter.register_post_delivery_callback(
        session_key,
        lambda: attempt_callbacks.append("release"),
    )
    adapter.register_post_delivery_callback(
        session_key,
        lambda: fired.append("cleanup"),
        success_only=True,
    )

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(_make_event(), session_key)

    assert fired == expected
    assert attempt_callbacks == ["release"]
    assert adapter.pop_post_delivery_callback(
        session_key,
        success_only=True,
    ) is None


@pytest.mark.asyncio
async def test_streamed_delivery_outcome_fires_success_only_callback_without_resend():
    adapter = _delete_adapter()
    adapter._send_with_retry = AsyncMock()
    fired = []
    session_key = "agent:main:telegram:private:42"

    async def _handler(evt):
        evt.delivery_outcome.record_success(already_sent=True)
        return None

    adapter.set_message_handler(_handler)
    adapter.register_post_delivery_callback(
        session_key,
        lambda: fired.append("cleanup"),
        success_only=True,
    )

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(_make_event(), session_key)

    adapter._send_with_retry.assert_not_awaited()
    assert fired == ["cleanup"]


@pytest.mark.asyncio
async def test_streamed_partial_delivery_outcome_retains_success_only_callback(caplog):
    caplog.set_level(logging.INFO, logger="gateway.platforms.base")
    adapter = _delete_adapter()
    adapter._send_with_retry = AsyncMock()
    fired = []
    session_key = "agent:main:telegram:private:42"

    async def _handler(evt):
        evt.delivery_outcome.record_success(already_sent=True)
        evt.delivery_outcome.record_failure("trailing media failed")
        return None

    adapter.set_message_handler(_handler)
    adapter.register_post_delivery_callback(
        session_key,
        lambda: fired.append("cleanup"),
        success_only=True,
    )

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(_make_event(), session_key)

    adapter._send_with_retry.assert_not_awaited()
    assert fired == []
    assert not any(
        getattr(record, "operation_card_event", None) == "retained"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_success_only_failure_hook_is_attributed_and_chained():
    adapter = _delete_adapter()
    adapter._send_with_retry = AsyncMock()
    fired = []
    retained = []
    session_key = "agent:main:telegram:private:42"

    async def _handler(evt):
        evt.delivery_outcome.record_failure("final delivery failed")
        return None

    def cleanup_one():
        fired.append("one")

    def cleanup_two():
        fired.append("two")

    cleanup_two._hermes_on_delivery_failed = lambda: retained.append("operation-card")
    adapter.set_message_handler(_handler)
    adapter.register_post_delivery_callback(
        session_key,
        cleanup_one,
        success_only=True,
    )
    adapter.register_post_delivery_callback(
        session_key,
        cleanup_two,
        success_only=True,
    )

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(_make_event(), session_key)

    assert fired == []
    assert retained == ["operation-card"]


@pytest.mark.asyncio
async def test_reused_event_starts_with_a_fresh_delivery_outcome():
    adapter = _delete_adapter()
    adapter._send_with_retry = AsyncMock(
        return_value=SendResult(success=True, message_id="second")
    )
    event = _make_event()
    event.delivery_outcome.record_failure("stale first attempt")
    session_key = "agent:main:telegram:private:42"
    fired = []

    async def _handler(evt):
        return "second response"

    adapter.set_message_handler(_handler)
    adapter.register_post_delivery_callback(
        session_key,
        lambda: fired.append("cleanup"),
        success_only=True,
    )

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(event, session_key)

    assert fired == ["cleanup"]
    assert event.delivery_outcome.failed_count == 0
    assert event.delivery_outcome.message_ids == ["second"]


def test_post_delivery_generation_mismatch_emits_structured_event(caplog):
    caplog.set_level(logging.INFO, logger="gateway.platforms.base")
    adapter = _delete_adapter()
    adapter.register_post_delivery_callback(
        "session-key",
        lambda: None,
        generation=2,
        success_only=True,
    )

    assert adapter.pop_post_delivery_callback(
        "session-key",
        generation=1,
        success_only=True,
    ) is None

    records = [
        record
        for record in caplog.records
        if getattr(record, "operation_card_event", None) == "generation_mismatch"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == "operation_card_lifecycle"
    assert "session-key" not in records[0].getMessage()


@pytest.mark.asyncio
async def test_legacy_callback_overrides_do_not_break_cleanup_or_session_release():
    adapter = _LegacyCallbackAdapter(
        PlatformConfig(enabled=True, token="t"),
        Platform.TELEGRAM,
    )
    adapter._send_with_retry = AsyncMock(
        return_value=SendResult(success=True, message_id="sent-1")
    )
    fired = []
    session_key = "agent:main:telegram:private:42"

    async def _handler(evt):
        return "final response"

    adapter.set_message_handler(_handler)
    BasePlatformAdapter.register_post_delivery_callback(
        adapter,
        session_key,
        lambda: fired.append("cleanup"),
        success_only=True,
    )
    adapter._session_tasks[session_key] = asyncio.current_task()

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(_make_event(), session_key)

    assert fired == ["cleanup"]
    assert session_key not in adapter._active_sessions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("send_success", "expected_callbacks"),
    [(True, ["cleanup"]), (False, [])],
)
async def test_document_only_final_controls_success_cleanup(
    tmp_path,
    send_success,
    expected_callbacks,
):
    adapter = _delete_adapter()
    document = tmp_path / "proof.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    adapter.send_document = AsyncMock(
        return_value=SendResult(
            success=send_success,
            message_id="doc-1" if send_success else None,
            error=None if send_success else "upload failed",
        )
    )
    fired = []
    session_key = "agent:main:telegram:private:42"

    async def _handler(evt):
        return f"MEDIA:{document}"

    adapter.set_message_handler(_handler)
    adapter.register_post_delivery_callback(
        session_key,
        lambda: fired.append("cleanup"),
        success_only=True,
    )

    with patch.object(adapter, "_keep_typing", new=AsyncMock()):
        await adapter._process_message_background(_make_event(), session_key)

    adapter.send_document.assert_awaited_once()
    assert fired == expected_callbacks


@pytest.mark.asyncio
async def test_process_message_incapable_platform_does_not_schedule_delete():
    adapter = _no_delete_adapter()
    adapter._send_with_retry = AsyncMock(
        return_value=SendResult(success=True, message_id="sent-1")
    )

    async def _handler(evt):
        return EphemeralReply("⚡ Stopped.", ttl_seconds=5)

    adapter.set_message_handler(_handler)

    # Spy on delete_message to confirm it is NOT invoked.
    delete_calls: list = []

    async def _spy_delete(chat_id, message_id):
        delete_calls.append((chat_id, message_id))
        return False

    adapter.delete_message = _spy_delete  # type: ignore[assignment]

    event = _make_event()
    session_key = "agent:main:telegram:private:42"
    with patch("gateway.platforms.base.asyncio.sleep", AsyncMock()), patch.object(
        adapter, "_keep_typing", new=AsyncMock()
    ):
        await adapter._process_message_background(event, session_key)
        for _ in range(10):
            await asyncio.sleep(0)

    # Send happened with the unwrapped text...
    adapter._send_with_retry.assert_called_once()
    assert adapter._send_with_retry.call_args.kwargs["content"] == "⚡ Stopped."
    # ...but delete was never scheduled because the capability check skipped
    # the schedule call (TTL was zeroed in _unwrap_ephemeral).
    # Note: the capability gate on _unwrap_ephemeral checks for
    # ``type(adapter).delete_message is BasePlatformAdapter.delete_message``.
    # Monkeypatching the instance does NOT change the class, so this test
    # verifies the gate uses the class method to detect capability.
    assert delete_calls == []


