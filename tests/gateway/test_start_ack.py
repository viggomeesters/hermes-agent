import asyncio
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.session import SessionSource, build_session_key


class StartAckAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True), Platform.TELEGRAM)
        self.sent = []

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id: str, content: str, **kwargs) -> SendResult:
        self.sent.append((chat_id, content, kwargs))
        return SendResult(success=True, message_id=f"sent-{len(self.sent)}")

    async def process_message(self, raw_message):
        return raw_message

    async def get_chat_info(self, chat_id: str):
        return {}


def _event(text="do work"):
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="chat-1",
            chat_type="dm",
            user_id="user-1",
        ),
        message_id="msg-1",
    )


@pytest.mark.asyncio
async def test_start_ack_sends_configured_text_for_fresh_turn(monkeypatch):
    adapter = StartAckAdapter()
    done = asyncio.Event()

    async def handler(_event):
        done.set()
        return "final"

    adapter.set_message_handler(handler)
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "display": {
                "platforms": {
                    "telegram": {
                        "start_ack": True,
                        "start_ack_text": "Ik heb ’m binnen; ik ga voor je aan de slag.",
                    }
                }
            }
        },
    )

    await adapter.handle_message(_event())
    await asyncio.wait_for(done.wait(), timeout=1)
    await asyncio.sleep(0)

    assert adapter.sent[0][1] == "Ik heb ’m binnen; ik ga voor je aan de slag."


@pytest.mark.asyncio
async def test_start_ack_can_include_bounded_message_scope(monkeypatch):
    adapter = StartAckAdapter()
    done = asyncio.Event()

    async def handler(_event):
        done.set()
        return "final"

    adapter.set_message_handler(handler)
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "display": {
                "platforms": {
                    "telegram": {
                        "start_ack": True,
                        "start_ack_text": (
                            "⚙️ Opgepakt: {scope}\n"
                            "Eerste inhoudelijke status: binnen ±1 min."
                        ),
                    }
                }
            }
        },
    )

    await adapter.handle_message(_event("Controleer   alle crons\nen herstel de rode jobs."))
    await asyncio.wait_for(done.wait(), timeout=1)
    await asyncio.sleep(0)

    assert adapter.sent[0][1] == (
        "⚙️ Opgepakt: Controleer alle crons en herstel de rode jobs.\n"
        "Eerste inhoudelijke status: binnen ±1 min."
    )


@pytest.mark.asyncio
async def test_start_ack_skips_slash_commands(monkeypatch):
    adapter = StartAckAdapter()
    adapter.set_message_handler(AsyncMock(return_value="status ok"))
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"display": {"platforms": {"telegram": {"start_ack": True, "start_ack_text": "working"}}}},
    )

    await adapter.handle_message(_event("/status"))
    await asyncio.sleep(0)

    assert all(content != "working" for _chat, content, _kwargs in adapter.sent)


@pytest.mark.asyncio
async def test_start_ack_send_failure_does_not_block_real_turn(monkeypatch):
    adapter = StartAckAdapter()
    done = asyncio.Event()

    async def handler(_event):
        done.set()
        return "final"

    adapter.set_message_handler(handler)
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"display": {"platforms": {"telegram": {"start_ack": True, "start_ack_text": "working"}}}},
    )
    send = AsyncMock(
        side_effect=[
            RuntimeError("telegram unavailable"),
            SendResult(success=True, message_id="final-1"),
        ]
    )
    monkeypatch.setattr(adapter, "_send_with_retry", send)

    await adapter.handle_message(_event())
    await asyncio.wait_for(done.wait(), timeout=1)
    await asyncio.sleep(0)

    assert send.await_args_list[0].kwargs["content"] == "working"
