import asyncio

import pytest

from gateway.notification_timing import FirstProgressDeadline, notification_delays


def test_notification_delays_keep_recurring_heartbeat_anchored_to_turn_start():
    delays = notification_delays(first_delay=60, interval=600)

    assert next(delays) == 60
    assert next(delays) == 540
    assert next(delays) == 600


@pytest.mark.asyncio
async def test_first_progress_deadline_fires_once_when_no_visible_progress():
    deadline = FirstProgressDeadline()

    assert deadline.should_notify() is True
    assert deadline.should_notify() is False


@pytest.mark.asyncio
async def test_visible_progress_suppresses_first_progress_deadline():
    deadline = FirstProgressDeadline()
    deadline.mark_visible()

    assert deadline.should_notify() is False
