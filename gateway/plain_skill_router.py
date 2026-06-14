"""Plain-text skill trigger routing for gateway messages."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def rewrite_plain_skill_trigger_event(event: Any, task_id: str | None = None) -> bool:
    """Rewrite leading plain-text skill triggers into skill invocation payloads.

    Slash commands already have a dedicated path. This catches command-like
    regular messages such as ``go now: fix X`` or ``go-now\n\n- fix X`` before
    they reach the model as ordinary prose.
    """
    try:
        from agent.skill_commands import build_plain_skill_invocation_message

        msg = build_plain_skill_invocation_message(
            getattr(event, "text", "") or "",
            task_id=task_id,
        )
    except Exception as exc:
        logger.debug("Plain skill trigger check failed (non-fatal): %s", exc)
        return False
    if not msg:
        return False
    try:
        event.text = msg
    except Exception:
        return False
    return True
