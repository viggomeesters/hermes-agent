"""Runtime copy-pack resolution for gateway-visible status text.

Core/gateway code should ask this module for user-facing operational copy
instead of hardcoding platform/persona-specific strings at call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gateway.display_config import resolve_display_setting


@dataclass(frozen=True)
class QueueCopy:
    """Queue lifecycle and busy/error copy for one runtime display pack."""

    current_complete: str
    queue_empty: str
    queue_full_current: str
    queue_full_drain: str
    queued_drain: str
    drain_not_accepting: str
    busy_queue: str
    busy_queue_subagent: str
    busy_steer: str
    busy_interrupt: str
    processing_error: str

    def format(self, key: str, **kwargs: Any) -> str:
        template = getattr(self, key)
        return template.format(**kwargs)


COPY_PACKS: dict[str, QueueCopy] = {
    "default": QueueCopy(
        current_complete="✅ Current task complete. Queue item {idx}/{total} → processing queued turn now.",
        queue_empty="✅ Queue empty.",
        queue_full_current=(
            "⚠️ Queue full ({count}/{max_pending}){status_detail}. "
            "I could not queue this message; please resend after the current task finishes."
        ),
        queue_full_drain=(
            "⚠️ Queue full — I could not queue this while the gateway is {action}. "
            "Please resend after it comes back."
        ),
        queued_drain="⏳ Gateway {action} — queued for the next turn after it comes back.",
        drain_not_accepting="⏳ Gateway is {action} and is not accepting another turn right now.",
        busy_queue=(
            "⏳ {queue_badge}{status_detail}. "
            "I’ll pick this up automatically once the current task finishes."
        ),
        busy_queue_subagent=(
            "⏳ {queue_badge}: subagent working{status_detail}. "
            "I’ll pick this up when it finishes (use /stop to cancel everything)."
        ),
        busy_steer=(
            "⏩ Steered into current run{status_detail}. "
            "Your message arrives after the next tool call."
        ),
        busy_interrupt="⚡ Interrupting current task{status_detail}. I'll respond to your message shortly.",
        processing_error=(
            "Sorry, I encountered an error ({error_type}).\n"
            "{error_detail}\n"
            "Try again or use /reset to start a fresh session."
        ),
    ),
    "bertus": QueueCopy(
        current_complete="Klus klaar. Ik pak backlog taak {idx} op.",
        queue_empty="Backlog leeg.",
        queue_full_current=(
            "Backlog vol ({count}/{max_pending}){status_detail}. "
            "Niet gelukt; stuur opnieuw als de huidige klus klaar is."
        ),
        queue_full_drain=(
            "Backlog vol — ik kon dit niet bewaren terwijl de gateway {action}. "
            "Stuur opnieuw zodra hij terug is."
        ),
        queued_drain="Gateway {action}. Ik heb dit in de backlog gezet.",
        drain_not_accepting="Gateway {action}; ik neem nu geen extra klus aan.",
        busy_queue=(
            "Ik ben al bezig; dit is backlog taak {count}{status_detail}. "
            "Ik pak ’m vanzelf op."
        ),
        busy_queue_subagent=(
            "Ik ben al bezig met subagents; dit is backlog taak {count}{status_detail}. "
            "Ik pak ’m op zodra die klus klaar is. /stop breekt alles af."
        ),
        busy_steer="Ik heb ’m bij de lopende klus gezet{status_detail}; na de volgende toolcall lees ik ’m mee.",
        busy_interrupt="Ik kap de huidige klus af{status_detail}. Ik pak je nieuwe bericht zo op.",
        processing_error=(
            "Daar ging iets stuk ({error_type}).\n"
            "Ik heb dit nodig: {error_detail}\n"
            "Niet gelukt; opnieuw sturen of /reset."
        ),
    ),
}


def normalize_copy_pack(value: Any) -> str:
    """Return a known copy-pack name, defaulting safely."""
    name = str(value or "").strip().lower().replace("_", "-")
    if name in {"", "none", "default", "generic", "hermes"}:
        return "default"
    if name in COPY_PACKS:
        return name
    return "default"


def resolve_copy_pack(config: dict | None, platform_key: str | None = None) -> str:
    """Resolve ``display.copy_pack`` with per-platform overrides."""
    cfg = config if isinstance(config, dict) else {}
    key = platform_key or ""
    value = resolve_display_setting(cfg, key, "copy_pack", "default")
    return normalize_copy_pack(value)


def copy_for(config: dict | None, platform_key: str | None = None) -> QueueCopy:
    """Return the resolved queue copy object."""
    return COPY_PACKS[resolve_copy_pack(config, platform_key)]
