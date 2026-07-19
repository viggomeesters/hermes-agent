"""Account-wide, cross-profile provider request concurrency leases.

Hermes profiles have isolated homes, but can share one provider account.  A
profile-local session cap therefore cannot prevent several gateways from
collectively exceeding an upstream account limit.  This module stores short
lived request leases under the shared Hermes root so every profile and process
participates in the same semaphore.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from hermes_constants import get_default_hermes_root

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderConcurrencySettings:
    max_concurrent_requests: int
    acquire_timeout_seconds: float = 900.0
    poll_interval_seconds: float = 0.2


class ProviderConcurrencyTimeout(TimeoutError):
    """Raised when no account-wide provider slot opens before the deadline."""


def _shared_root() -> Path:
    return Path(get_default_hermes_root())


def _state_path() -> Path:
    return _shared_root() / "runtime" / "provider_requests.json"


def _lock_path() -> Path:
    return _shared_root() / "runtime" / "provider_requests.lock"


def _positive_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _load_provider_settings(provider: str) -> Optional[ProviderConcurrencySettings]:
    """Load the shared-root provider cap, independent of the active profile."""
    config_path = _shared_root() / "config.yaml"
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("Ignoring unreadable provider concurrency config at %s", config_path)
        return None

    section = data.get("provider_concurrency") if isinstance(data, dict) else None
    raw = section.get(provider) if isinstance(section, dict) else None
    if not isinstance(raw, dict):
        return None
    limit = _positive_int(raw.get("max_concurrent_requests"))
    if limit is None:
        return None
    return ProviderConcurrencySettings(
        max_concurrent_requests=limit,
        acquire_timeout_seconds=_positive_float(raw.get("acquire_timeout_seconds"), 900.0),
        poll_interval_seconds=_positive_float(raw.get("poll_interval_seconds"), 0.2),
    )


class _FileLock:
    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        if os.name == "nt":
            import msvcrt

            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def _read_entries(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        logger.warning("Ignoring corrupt provider request registry at %s", path)
        return []
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _write_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps({"entries": entries}, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _process_start_time(pid: int) -> Optional[float]:
    try:
        import psutil  # type: ignore

        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def _pid_alive(pid: Any, process_start_time: Any = None) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        from gateway.status import _pid_exists

        if not _pid_exists(pid_int):
            return False
    except Exception:
        return False
    if process_start_time in (None, ""):
        return True
    try:
        expected = float(process_start_time)
    except (TypeError, ValueError):
        return True
    current = _process_start_time(pid_int)
    return current is None or abs(current - expected) < 0.001


def _prune_dead(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if _pid_alive(entry.get("pid"), entry.get("process_start_time"))
    ]


@dataclass
class ProviderRequestLease:
    lease_id: str
    provider: str
    purpose: str
    enabled: bool = True
    released: bool = False

    def release(self) -> None:
        if not self.released and self.enabled:
            release_provider_request(self)


def acquire_provider_request(provider: str, *, purpose: str = "primary") -> ProviderRequestLease:
    settings = _load_provider_settings(provider)
    lease_id = uuid.uuid4().hex
    if settings is None:
        return ProviderRequestLease(lease_id, provider, purpose, enabled=False)

    deadline = time.monotonic() + settings.acquire_timeout_seconds
    logged_wait = False
    while True:
        now = time.time()
        entry = {
            "lease_id": lease_id,
            "provider": str(provider),
            "purpose": str(purpose),
            "pid": os.getpid(),
            "process_start_time": _process_start_time(os.getpid()),
            "started_at": now,
        }
        state_path = _state_path()
        with _FileLock(_lock_path()):
            raw_entries = _read_entries(state_path)
            entries = _prune_dead(raw_entries)
            active = sum(1 for item in entries if item.get("provider") == provider)
            if active < settings.max_concurrent_requests:
                entries.append(entry)
                _write_entries(state_path, entries)
                if logged_wait:
                    logger.info(
                        "Acquired shared provider slot: provider=%s active=%d max=%d",
                        provider,
                        active + 1,
                        settings.max_concurrent_requests,
                    )
                return ProviderRequestLease(lease_id, provider, purpose)
            if len(entries) != len(raw_entries):
                _write_entries(state_path, entries)

        if time.monotonic() >= deadline:
            raise ProviderConcurrencyTimeout(
                f"Timed out waiting for shared {provider} request slot "
                f"(max {settings.max_concurrent_requests})"
            )
        if not logged_wait:
            logger.info(
                "Waiting for shared provider slot: provider=%s active=%d max=%d purpose=%s",
                provider,
                active,
                settings.max_concurrent_requests,
                purpose,
            )
            logged_wait = True
        time.sleep(settings.poll_interval_seconds)


def release_provider_request(lease: ProviderRequestLease) -> None:
    try:
        with _FileLock(_lock_path()):
            entries = _prune_dead(_read_entries(_state_path()))
            kept = [entry for entry in entries if entry.get("lease_id") != lease.lease_id]
            if len(kept) != len(entries):
                _write_entries(_state_path(), kept)
    finally:
        lease.released = True


@contextmanager
def provider_request_slot(provider: str, *, purpose: str = "primary") -> Iterator[ProviderRequestLease]:
    lease = acquire_provider_request(provider, purpose=purpose)
    try:
        yield lease
    finally:
        lease.release()


def provider_request_registry_snapshot() -> list[dict[str, Any]]:
    with _FileLock(_lock_path()):
        entries = _prune_dead(_read_entries(_state_path()))
        _write_entries(_state_path(), entries)
        return entries