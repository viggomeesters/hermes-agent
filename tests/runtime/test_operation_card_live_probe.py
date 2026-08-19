"""Opt-in live Telegram proof for the editable operation-card lifecycle."""
from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from gateway.display_config import resolve_display_setting
from gateway.notification_timing import notification_delays
from gateway.operation_card_controller import OperationCardController
from gateway.platforms.base import SendResult
from gateway.run import _load_gateway_config


@pytest.mark.asyncio
async def test_failed_delivery_probe_retains_card_breadcrumb():
    cleanup_ids: list[str] = []
    responses = [
        (SendResult(success=True, message_id="card-1"), "card-1"),
        (SendResult(success=False, message_id="card-1", error="delivery failed"), "card-1"),
    ]

    async def send(previous_id, text):
        return responses.pop(0)

    controller = OperationCardController(
        enabled=True,
        phase_interval=0,
        cleanup_enabled=True,
        cleanup_message_ids=cleanup_ids,
        context_id="safe-failure-probe",
    )
    await controller.update(render=lambda: "running", send=send)
    await controller.update(render=lambda: "failed edit", send=send, status="failed")
    controller.record_retained("final_delivery_failed")

    assert controller.message_id == "card-1"
    assert cleanup_ids == ["card-1"]
    assert controller.terminal is True


@pytest.mark.asyncio
async def test_live_telegram_operation_card_10_15_180_and_cleanup():
    if os.getenv("HERMES_LIVE_TELEGRAM_PROBE") != "1":
        pytest.skip("set HERMES_LIVE_TELEGRAM_PROBE=1 for the real Telegram probe")

    from telegram import Bot

    config = _load_gateway_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "")
    assert token and chat_id

    first_delay = float(os.environ["HERMES_AGENT_FIRST_NOTIFY_DELAY"])
    notify_interval = float(os.environ["HERMES_AGENT_NOTIFY_INTERVAL"])
    phase_interval = float(
        resolve_display_setting(
            config,
            "telegram",
            "operation_card_phase_update_interval",
            15.0,
        )
    )
    assert (first_delay, phase_interval, notify_interval) == (10.0, 15.0, 180.0)

    cleanup_ids: list[str] = []
    controller = OperationCardController(
        enabled=True,
        phase_interval=phase_interval,
        cleanup_enabled=True,
        cleanup_message_ids=cleanup_ids,
        context_id="live-telegram-probe",
    )
    bot = Bot(token=token)
    await bot.initialize()

    started = time.monotonic()
    send_times: list[float] = []
    message_ids: list[str] = []
    phase = ["agent actief"]

    def render(status: str = "running") -> str:
        status_text = "✅ afgerond" if status == "completed" else "🟢 actief"
        return (
            "⚙️ Operatie\n"
            f"Status: {status_text}\n"
            f"Fase: {phase[0]}\n"
            "Voortgang: live Telegram probe\n"
            "ETA: onbekend\n"
            "Worker: runtime-proof\n"
            f"Bijgewerkt: {time.strftime('%H:%M:%S')}"
        )

    async def send(previous_id: str | None, text: str):
        if previous_id:
            message = await bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(previous_id),
                text=text,
            )
        else:
            message = await bot.send_message(chat_id=chat_id, text=text)
        message_id = str(message.message_id)
        send_times.append(time.monotonic())
        message_ids.append(message_id)
        return SendResult(success=True, message_id=message_id), message_id

    deleted = False
    try:
        delays = notification_delays(
            first_delay=first_delay,
            interval=notify_interval,
        )
        await asyncio.sleep(next(delays))
        await controller.update(render=render, send=send)
        created_at = send_times[-1]

        phase[0] = "read file"
        phase_task = asyncio.create_task(
            controller.update(
                render=render,
                send=send,
                dedupe_unchanged=True,
            )
        )

        await asyncio.sleep(next(delays))
        await controller.update(render=render, send=send)
        await phase_task
        heartbeat_at = send_times[-1]

        phase[0] = "afronden"
        await controller.update(
            render=lambda: render("completed"),
            send=send,
            status="completed",
        )

        assert created_at - started >= first_delay - 0.5
        assert send_times[1] - created_at >= phase_interval - 0.5
        assert heartbeat_at - started <= notify_interval + 5.0
        assert len(set(message_ids)) == 1
        assert cleanup_ids == [message_ids[0]]

        deleted = bool(
            await bot.delete_message(chat_id=chat_id, message_id=int(message_ids[0]))
        )
        assert deleted is True
        controller.record_removed("live_probe_cleanup_succeeded")

        print(
            "LIVE_PROBE_JSON="
            + json.dumps(
                {
                    "message_id": message_ids[0],
                    "unique_message_ids": len(set(message_ids)),
                    "creation_delay_seconds": round(created_at - started, 3),
                    "phase_gap_seconds": round(send_times[1] - created_at, 3),
                    "heartbeat_from_start_seconds": round(heartbeat_at - started, 3),
                    "telegram_delete_succeeded": deleted,
                    "timing_policy": [first_delay, phase_interval, notify_interval],
                },
                sort_keys=True,
            )
        )
    finally:
        if message_ids and not deleted:
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=int(message_ids[0]),
                )
            except Exception:
                pass
        await bot.shutdown()
