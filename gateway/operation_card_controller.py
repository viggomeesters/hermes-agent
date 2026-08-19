"""Single-owner lifecycle state for editable operation cards."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Optional


RenderCard = Callable[[], str]
SendCard = Callable[[Optional[str], str], Awaitable[tuple[Any, Optional[str]]]]
logger = logging.getLogger(__name__)


class OperationCardController:
    """Own operation-card phase, rate-limit, dedupe, terminal, and cleanup state."""

    def __init__(
        self,
        *,
        enabled: bool,
        phase_interval: float,
        cleanup_enabled: bool = False,
        cleanup_message_ids: Optional[list[str]] = None,
        context_id: str = "",
        loop: Optional[asyncio.AbstractEventLoop] = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.enabled = bool(enabled)
        self.phase_interval = max(0.0, float(phase_interval))
        self.cleanup_enabled = bool(cleanup_enabled)
        self.cleanup_message_ids = (
            cleanup_message_ids if cleanup_message_ids is not None else []
        )
        self.context_id = str(context_id or "")[:64]
        self.loop = loop
        self.monotonic = monotonic
        self.sleep = sleep

        self.message_id: Optional[str] = None
        self.phase: Optional[str] = None
        self.phase_event = asyncio.Event()
        self.update_lock = asyncio.Lock()
        self.last_edit = 0.0
        self.last_semantic_key: Optional[str] = None
        self.terminal = False

    def _emit(
        self,
        event: str,
        *,
        reason: str = "",
        status: str = "",
    ) -> None:
        logger.info(
            "operation_card_lifecycle",
            extra={
                "operation_card_event": str(event)[:32],
                "operation_card_context": self.context_id,
                "operation_card_reason": str(reason or "")[:64],
                "operation_card_status": str(status or "")[:32],
                "operation_card_has_message_id": bool(self.message_id),
            },
        )

    def record_retained(self, reason: str) -> None:
        self._emit("retained", reason=reason)

    def record_removed(self, reason: str) -> None:
        self._emit("removed", reason=reason)

    @staticmethod
    def semantic_key(text: str) -> str:
        """Ignore the liveness timestamp for phase-only deduplication."""
        return "\n".join(
            line for line in text.splitlines()
            if not line.startswith("Bijgewerkt:")
        )

    def request_phase_update(self, event_type: str, tool_name: str) -> None:
        del event_type
        if not self.enabled:
            return
        self.phase = " ".join(str(tool_name).split("_")).strip()
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.phase_event.set)
        else:
            self.phase_event.set()

    def clear_phase_event(self) -> None:
        self.phase_event.clear()

    async def update(
        self,
        *,
        render: RenderCard,
        send: SendCard,
        status: str = "running",
        dedupe_unchanged: bool = False,
    ) -> tuple[Any, Optional[str]]:
        """Render and send/edit one card while enforcing shared lifecycle policy."""
        while True:
            delay = 0.0
            async with self.update_lock:
                if status == "running" and self.terminal:
                    return None, self.message_id

                previous_id = self.message_id
                if previous_id and status == "running":
                    delay = self.phase_interval - (self.monotonic() - self.last_edit)
                if delay <= 0:
                    if status != "running":
                        self.terminal = True
                    card_text = render()
                    semantic_key = self.semantic_key(card_text)
                    if (
                        dedupe_unchanged
                        and status == "running"
                        and previous_id
                        and semantic_key == self.last_semantic_key
                    ):
                        self._emit(
                            "coalesced",
                            reason="semantic_state_unchanged",
                            status=status,
                        )
                        return None, previous_id

                    result, next_id = await send(previous_id, card_text)
                    if next_id and bool(getattr(result, "success", False)):
                        self.message_id = str(next_id)
                        self.last_edit = self.monotonic()
                        self.last_semantic_key = semantic_key
                        if (
                            self.cleanup_enabled
                            and self.message_id not in self.cleanup_message_ids
                        ):
                            self.cleanup_message_ids.append(self.message_id)
                        self._emit(
                            "edited" if previous_id else "created",
                            reason="transport_success",
                            status=status,
                        )
                    return result, next_id

            await self.sleep(delay)
