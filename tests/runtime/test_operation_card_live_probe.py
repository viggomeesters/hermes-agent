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


def _assert_live_timing(
    *,
    creation_delay: float,
    phase_gap: float,
    heartbeat_from_start: float,
    operation_count: int,
    first_delay: float = 10.0,
    phase_interval: float = 15.0,
    notify_interval: float = 180.0,
) -> None:
    assert first_delay - 0.5 <= creation_delay <= first_delay + 10.0
    assert phase_interval - 0.5 <= phase_gap <= phase_interval + 10.0
    assert notify_interval - 0.5 <= heartbeat_from_start <= notify_interval + 10.0
    assert operation_count == 4


async def _delete_live_probe_message(bot, *, chat_id: str, message_id: str) -> bool:
    try:
        deleted = bool(
            await bot.delete_message(
                chat_id=chat_id,
                message_id=int(message_id),
            )
        )
    except Exception as exc:
        raise AssertionError(
            f"Telegram live-probe cleanup failed; retained message_id={message_id}"
        ) from exc
    if not deleted:
        raise AssertionError(
            f"Telegram live-probe cleanup failed; retained message_id={message_id}"
        )
    return True


@pytest.mark.parametrize(
    ("creation_delay", "phase_gap", "heartbeat_from_start", "operation_count"),
    [
        (60.0, 15.0, 180.0, 4),
        (10.0, 40.0, 180.0, 4),
        (10.0, 15.0, 25.0, 4),
        (10.0, 15.0, 180.0, 1),
    ],
)
def test_live_timing_policy_rejects_false_positive_proof(
    creation_delay,
    phase_gap,
    heartbeat_from_start,
    operation_count,
):
    with pytest.raises(AssertionError):
        _assert_live_timing(
            creation_delay=creation_delay,
            phase_gap=phase_gap,
            heartbeat_from_start=heartbeat_from_start,
            operation_count=operation_count,
        )


@pytest.mark.asyncio
async def test_live_cleanup_failure_reports_retained_message_id():
    class DeleteFails:
        async def delete_message(self, **kwargs):
            return False

    with pytest.raises(AssertionError, match="retained message_id=4242"):
        await _delete_live_probe_message(
            DeleteFails(),
            chat_id="home",
            message_id="4242",
        )


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

        _assert_live_timing(
            creation_delay=created_at - started,
            phase_gap=send_times[1] - created_at,
            heartbeat_from_start=heartbeat_at - started,
            operation_count=len(send_times),
            first_delay=first_delay,
            phase_interval=phase_interval,
            notify_interval=notify_interval,
        )
        assert len(set(message_ids)) == 1
        assert cleanup_ids == [message_ids[0]]

        deleted = await _delete_live_probe_message(
            bot,
            chat_id=chat_id,
            message_id=message_ids[0],
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
        cleanup_error = None
        try:
            if message_ids and not deleted:
                deleted = await _delete_live_probe_message(
                    bot,
                    chat_id=chat_id,
                    message_id=message_ids[0],
                )
        except AssertionError as exc:
            cleanup_error = exc
        finally:
            await bot.shutdown()
        if cleanup_error is not None:
            raise cleanup_error
