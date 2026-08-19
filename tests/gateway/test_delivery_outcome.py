from gateway.delivery import DeliveryOutcome
from gateway.platforms.base import MessageEvent, SendResult


def test_delivery_outcome_requires_attempt_and_zero_failures_for_cleanup():
    outcome = DeliveryOutcome()

    assert outcome.attempted is False
    assert outcome.cleanup_succeeded is False

    outcome.record_result(SendResult(success=True, message_id="one"))

    assert outcome.attempted_count == 1
    assert outcome.succeeded_count == 1
    assert outcome.failed_count == 0
    assert outcome.cleanup_succeeded is True

    outcome.record_result(SendResult(success=False, error="second failed"))

    assert outcome.attempted_count == 2
    assert outcome.succeeded_count == 1
    assert outcome.failed_count == 1
    assert outcome.cleanup_succeeded is False


def test_delivery_outcome_merge_preserves_all_attempts():
    body = DeliveryOutcome()
    body.record_success(message_id="body")
    media = DeliveryOutcome()
    media.record_failure("media failed")

    body.merge(media)

    assert body.attempted_count == 2
    assert body.succeeded_count == 1
    assert body.failed_count == 1
    assert body.message_ids == ["body"]
    assert body.last_error == "media failed"


def test_message_event_owns_a_fresh_delivery_outcome():
    first = MessageEvent(text="one")
    second = MessageEvent(text="two")

    first.delivery_outcome.record_success()

    assert first.delivery_outcome.attempted_count == 1
    assert second.delivery_outcome.attempted_count == 0


def test_none_result_is_a_failed_attempt_not_missing_evidence():
    outcome = DeliveryOutcome()

    outcome.record_result(None)

    assert outcome.attempted_count == 1
    assert outcome.failed_count == 1
    assert outcome.cleanup_succeeded is False
    assert outcome.last_error == "Delivery returned no result"
