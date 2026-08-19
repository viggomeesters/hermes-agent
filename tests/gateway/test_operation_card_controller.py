import asyncio
import logging

import pytest

from gateway.operation_card_controller import OperationCardController
from gateway.platforms.base import SendResult


@pytest.mark.asyncio
async def test_controller_owns_rate_limit_dedupe_heartbeat_and_terminal():
    now = [100.0]
    cleanup_ids = []
    sends = []

    async def sleep(delay):
        now[0] += delay

    async def send(previous_id, text):
        sends.append((previous_id, text))
        next_id = previous_id or "card-1"
        return SendResult(success=True, message_id=next_id), next_id

    controller = OperationCardController(
        enabled=True,
        phase_interval=15.0,
        cleanup_enabled=True,
        cleanup_message_ids=cleanup_ids,
        monotonic=lambda: now[0],
        sleep=sleep,
    )

    await controller.update(
        render=lambda: "Status: running\nFase: patch\nBijgewerkt: 09:00:00",
        send=send,
    )
    await controller.update(
        render=lambda: "Status: running\nFase: patch\nBijgewerkt: 09:00:15",
        send=send,
        dedupe_unchanged=True,
    )
    await controller.update(
        render=lambda: "Status: running\nFase: patch\nBijgewerkt: 09:00:30",
        send=send,
    )
    await controller.update(
        render=lambda: "Status: completed\nFase: patch\nBijgewerkt: 09:00:31",
        send=send,
        status="completed",
        dedupe_unchanged=True,
    )

    assert controller.message_id == "card-1"
    assert cleanup_ids == ["card-1"]
    assert len(sends) == 3
    assert sends[0][0] is None
    assert sends[1][0] == "card-1"  # heartbeat bypasses semantic dedupe
    assert sends[2][0] == "card-1"  # terminal update bypasses running dedupe
    assert controller.terminal is True


@pytest.mark.asyncio
async def test_controller_records_state_only_after_successful_send_id():
    calls = []

    async def send(previous_id, text):
        calls.append((previous_id, text))
        return None, None

    controller = OperationCardController(enabled=True, phase_interval=0)

    await controller.update(render=lambda: "same", send=send)
    await controller.update(
        render=lambda: "same",
        send=send,
        dedupe_unchanged=True,
    )

    assert len(calls) == 2
    assert controller.message_id is None


@pytest.mark.asyncio
async def test_failed_edit_with_existing_id_does_not_poison_dedupe_state():
    responses = [
        (SendResult(success=True, message_id="card-1"), "card-1"),
        (SendResult(success=False, message_id="card-1", error="edit failed"), "card-1"),
        (SendResult(success=True, message_id="card-1"), "card-1"),
    ]
    sends = []

    async def send(previous_id, text):
        sends.append((previous_id, text))
        return responses.pop(0)

    controller = OperationCardController(enabled=True, phase_interval=0)
    await controller.update(render=lambda: "phase one", send=send)
    await controller.update(
        render=lambda: "phase two",
        send=send,
        dedupe_unchanged=True,
    )
    await controller.update(
        render=lambda: "phase two",
        send=send,
        dedupe_unchanged=True,
    )

    assert len(sends) == 3


@pytest.mark.asyncio
async def test_controller_phase_callback_updates_phase_and_event():
    controller = OperationCardController(
        enabled=True,
        phase_interval=15,
        loop=asyncio.get_running_loop(),
    )

    controller.request_phase_update("tool.started", "read_file")
    await asyncio.wait_for(controller.phase_event.wait(), timeout=0.2)

    assert controller.phase == "read file"


@pytest.mark.asyncio
async def test_controller_emits_bounded_structured_lifecycle_events(caplog):
    caplog.set_level(logging.INFO, logger="gateway.operation_card_controller")
    responses = [
        (SendResult(success=True, message_id="card-1"), "card-1"),
        (SendResult(success=True, message_id="card-1"), "card-1"),
    ]

    async def send(previous_id, text):
        return responses.pop(0)

    controller = OperationCardController(
        enabled=True,
        phase_interval=0,
        context_id="ctx-123",
    )
    await controller.update(render=lambda: "phase one", send=send)
    await controller.update(
        render=lambda: "phase one",
        send=send,
        dedupe_unchanged=True,
    )
    await controller.update(render=lambda: "phase two", send=send)
    controller.record_retained("final_delivery_failed")
    controller.record_removed("final_delivery_succeeded")

    records = [
        record
        for record in caplog.records
        if getattr(record, "operation_card_event", None)
    ]
    assert [record.operation_card_event for record in records] == [
        "created",
        "coalesced",
        "edited",
        "retained",
        "removed",
    ]
    assert {record.operation_card_context for record in records} == {"ctx-123"}
    assert all(record.getMessage() == "operation_card_lifecycle" for record in records)
    assert all("phase one" not in record.getMessage() for record in records)
