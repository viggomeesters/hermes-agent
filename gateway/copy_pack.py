"""Runtime copy-pack resolution for gateway-visible status text.

Core/gateway code should ask this module for user-facing operational copy
instead of hardcoding platform/persona-specific strings at call sites.

External packs can be loaded from JSON files in ``display.copy_pack_dirs``.
That keeps personal or deployment-specific copy out of Hermes core while the
core retains generic schema/resolution behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
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


_REQUIRED_QUEUE_COPY_KEYS = tuple(field.name for field in fields(QueueCopy))


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
    # Back-compat for existing deployments. New deployment-specific copy should
    # live in JSON files loaded via display.copy_pack_dirs, not in Hermes core.
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


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _coerce_copy_pack_dirs(config: dict | None) -> list[Path]:
    cfg = config if isinstance(config, dict) else {}
    display = cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
    raw_dirs = display.get("copy_pack_dirs", [])
    if isinstance(raw_dirs, (str, Path)):
        raw_dirs = [raw_dirs]
    if not isinstance(raw_dirs, list):
        return []
    dirs: list[Path] = []
    for raw in raw_dirs:
        if not raw:
            continue
        try:
            dirs.append(Path(str(raw)).expanduser())
        except Exception:
            continue
    return dirs


def _queue_copy_from_payload(payload: dict[str, Any], source: Path) -> tuple[str, QueueCopy] | None:
    name = _normalize_name(payload.get("name") or source.stem)
    if not name or name in {"none", "generic", "hermes"}:
        return None
    messages = payload.get("messages") if isinstance(payload.get("messages"), dict) else payload
    if not isinstance(messages, dict):
        return None
    values: dict[str, str] = {}
    for key in _REQUIRED_QUEUE_COPY_KEYS:
        value = messages.get(key)
        if not isinstance(value, str) or not value:
            return None
        values[key] = value
    return name, QueueCopy(**values)


def load_external_copy_packs(config: dict | None) -> dict[str, QueueCopy]:
    """Load JSON copy packs from ``display.copy_pack_dirs``.

    Invalid files are ignored fail-closed: unknown or broken deployment copy
    should never prevent the gateway from falling back to default copy.
    """

    packs: dict[str, QueueCopy] = {}
    for directory in _coerce_copy_pack_dirs(config):
        try:
            candidates = sorted(directory.glob("*.json")) if directory.is_dir() else []
        except Exception:
            continue
        for path in candidates:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                parsed = _queue_copy_from_payload(loaded, path)
            except Exception:
                parsed = None
            if parsed is None:
                continue
            name, copy = parsed
            packs[name] = copy
    return packs


def available_copy_packs(config: dict | None = None) -> dict[str, QueueCopy]:
    """Return built-in packs plus externally configured packs.

    External packs override built-ins by name so a deployment can migrate a
    previously built-in persona out of core without changing config references.
    """

    packs = dict(COPY_PACKS)
    packs.update(load_external_copy_packs(config))
    return packs


def normalize_copy_pack(value: Any, config: dict | None = None) -> str:
    """Return a known copy-pack name, defaulting safely."""

    name = _normalize_name(value)
    if name in {"", "none", "default", "generic", "hermes"}:
        return "default"
    if name in available_copy_packs(config):
        return name
    return "default"


def resolve_copy_pack(config: dict | None, platform_key: str | None = None) -> str:
    """Resolve ``display.copy_pack`` with per-platform overrides."""
    cfg = config if isinstance(config, dict) else {}
    key = platform_key or ""
    value = resolve_display_setting(cfg, key, "copy_pack", "default")
    return normalize_copy_pack(value, cfg)


def copy_for(config: dict | None, platform_key: str | None = None) -> QueueCopy:
    """Return the resolved queue copy object."""

    cfg = config if isinstance(config, dict) else {}
    packs = available_copy_packs(cfg)
    return packs[resolve_copy_pack(cfg, platform_key)]
