from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.platforms.base import SendResult, aggregate_send_results
from gateway.platforms.signal import SignalAdapter
from plugins.platforms.discord.adapter import DiscordAdapter
from plugins.platforms.email.adapter import EmailAdapter
from plugins.platforms.matrix.adapter import MatrixAdapter
from plugins.platforms.mattermost.adapter import MattermostAdapter
from plugins.platforms.slack.adapter import SlackAdapter


@pytest.mark.asyncio
async def test_matrix_multi_image_reports_partial_failure():
    adapter = object.__new__(MatrixAdapter)
    adapter.send_image = AsyncMock(
        side_effect=[
            SendResult(success=True, message_id="first"),
            SendResult(success=False, error="second failed"),
        ]
    )

    result = await MatrixAdapter.send_multiple_images(
        adapter,
        "room",
        [("https://example.com/1.png", "one"), ("https://example.com/2.png", "two")],
    )

    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.message_id == "first"
    assert result.error == "second failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_class", "setup"),
    [
        (SignalAdapter, lambda adapter: None),
        (DiscordAdapter, lambda adapter: setattr(adapter, "_client", None)),
        (EmailAdapter, lambda adapter: None),
        (MatrixAdapter, lambda adapter: None),
        (MattermostAdapter, lambda adapter: None),
        (
            SlackAdapter,
            lambda adapter: (
                setattr(adapter, "_ignored_channels", set()),
                setattr(adapter, "_app", None),
            ),
        ),
    ],
)
async def test_multi_image_overrides_fail_explicitly_for_empty_input(adapter_class, setup):
    adapter = object.__new__(adapter_class)
    setup(adapter)

    result = await adapter_class.send_multiple_images(adapter, "chat", [])

    assert isinstance(result, SendResult)
    assert result.success is False


@pytest.mark.asyncio
async def test_email_multi_image_returns_smtp_message_id():
    adapter = object.__new__(EmailAdapter)
    adapter._send_email_with_attachments = lambda *_args: "mail-1"

    result = await EmailAdapter.send_multiple_images(
        adapter,
        "to@example.com",
        [("https://example.com/image.png", "caption")],
    )

    assert result == SendResult(success=True, message_id="mail-1")


def test_multi_image_overrides_declare_send_result_contract():
    for adapter_class in (
        SignalAdapter,
        DiscordAdapter,
        EmailAdapter,
        MatrixAdapter,
        MattermostAdapter,
        SlackAdapter,
    ):
        assert adapter_class.send_multiple_images.__annotations__["return"] in (
            SendResult,
            "SendResult",
        )


def test_aggregate_send_results_is_fail_closed_for_partial_delivery():
    result = aggregate_send_results(
        [
            SendResult(success=True, message_id="delivered"),
            SendResult(success=False, error="second failed"),
        ]
    )

    assert result == SendResult(
        success=False,
        message_id="delivered",
        error="second failed",
    )


def test_aggregate_preserves_failure_metadata_and_ignores_failed_message_id():
    result = aggregate_send_results(
        [
            SendResult(success=True, message_id="delivered"),
            SendResult(
                success=False,
                message_id="failed-visible",
                error="transient",
                raw_response={"provider": "fallback"},
                retryable=True,
                retry_after=3.5,
                continuation_message_ids=("continuation",),
                error_kind="transient",
            ),
        ]
    )

    assert result.message_id == "delivered"
    assert result.raw_response == {"provider": "fallback"}
    assert result.retryable is True
    assert result.retry_after == 3.5
    assert result.continuation_message_ids == ("continuation",)
    assert result.error_kind == "transient"


@pytest.mark.asyncio
async def test_matrix_multi_image_fails_before_sending_missing_local_file(tmp_path):
    adapter = object.__new__(MatrixAdapter)
    adapter.send_image_file = AsyncMock(return_value=SendResult(success=True))
    missing = tmp_path / "missing.png"

    result = await MatrixAdapter.send_multiple_images(
        adapter,
        "room",
        [(f"file://{missing}", "missing")],
    )

    assert result.success is False
    adapter.send_image_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_matrix_multi_image_converts_sender_exception_to_failure():
    adapter = object.__new__(MatrixAdapter)
    adapter.send_image = AsyncMock(side_effect=OSError("matrix unavailable"))

    result = await MatrixAdapter.send_multiple_images(
        adapter,
        "room",
        [("https://example.com/image.png", "image")],
    )

    assert result == SendResult(success=False, error="matrix unavailable")


def test_email_attachment_read_failure_stops_before_smtp(tmp_path, monkeypatch):
    adapter = object.__new__(EmailAdapter)
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    adapter._address = "agent@example.com"
    adapter._thread_context = {}
    adapter._connect_smtp = MagicMock()
    monkeypatch.setattr("builtins.open", MagicMock(side_effect=OSError("read failed")))

    with pytest.raises(RuntimeError, match="Failed to attach"):
        adapter._send_email_with_attachments("to@example.com", "body", [str(image)])

    adapter._connect_smtp.assert_not_called()


@pytest.mark.asyncio
async def test_slack_multi_image_reads_timestamp_from_mapping_like_response(tmp_path):
    class MappingResponse:
        def __getitem__(self, key):
            return {"ts": "123.456"}.get(key)

    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    client = MagicMock()
    client.files_upload_v2 = AsyncMock(return_value=MappingResponse())
    adapter = object.__new__(SlackAdapter)
    adapter._app = object()
    adapter._is_ignored_channel = lambda _chat_id: False
    adapter._ensure_dm_conversation = AsyncMock(return_value="chat")
    adapter._metadata_team_id = lambda _metadata: None
    adapter._resolve_thread_ts = lambda _reply_to, _metadata: None
    adapter._get_client = lambda *_args, **_kwargs: client
    adapter._record_uploaded_file_thread = lambda *_args, **_kwargs: None

    result = await SlackAdapter.send_multiple_images(
        adapter,
        "chat",
        [(f"file://{image}", "image")],
    )

    assert result == SendResult(success=True, message_id="123.456")


@pytest.mark.asyncio
async def test_signal_multi_image_converts_preparation_exception_to_failure(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    adapter = object.__new__(SignalAdapter)
    adapter._stop_typing_indicator = AsyncMock(side_effect=OSError("signal unavailable"))

    result = await SignalAdapter.send_multiple_images(
        adapter,
        "+15551234567",
        [(f"file://{image}", "image")],
    )

    assert result == SendResult(success=False, error="signal unavailable")
