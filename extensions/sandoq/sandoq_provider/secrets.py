"""Short-lived, permission-checked cache for local secret files."""

from __future__ import annotations

import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

_DEFAULT_CACHE_TTL_SECONDS = 5.0
_Error = TypeVar("_Error", bound=Exception)


@dataclass
class _CacheEntry:
    value: str
    checked_at: float


_cache: dict[tuple[Path, str, type[Exception]], _CacheEntry] = {}
_cache_lock = threading.Lock()


def _cache_ttl_seconds() -> float:
    value = os.environ.get("OCI_RUNNER_SECRET_CACHE_TTL", "").strip().lower()
    if not value:
        return _DEFAULT_CACHE_TTL_SECONDS
    for suffix, multiplier in (("ms", 0.001), ("s", 1.0), ("m", 60.0)):
        if value.endswith(suffix):
            return max(float(value[: -len(suffix)]) * multiplier, 0.0)
    return max(float(value), 0.0)


def read_secret_file(path: Path, label: str, error_type: type[_Error]) -> str:
    """Read one mode-0600 regular file, caching it briefly between validations.

    The descriptor is opened with ``O_NOFOLLOW`` where available, then validated
    with ``fstat`` so symlink swaps and permission changes are rejected whenever
    the short cache window expires. Atomic replacement is picked up on the next
    refresh, preserving token rotation without filesystem traffic per request.
    """
    resolved = Path(path)
    key = (resolved, label, error_type)
    now = time.monotonic()
    ttl = _cache_ttl_seconds()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and now - cached.checked_at < ttl:
            return cached.value

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(resolved, flags)
        except OSError as exc:
            raise error_type(f"{label} file cannot be opened safely: {resolved} ({type(exc).__name__})") from exc
        try:
            file_stat = os.fstat(descriptor)
            mode = stat.S_IMODE(file_stat.st_mode)
            if not stat.S_ISREG(file_stat.st_mode) or mode != 0o600:
                raise error_type(f"{label} file must be a regular mode-0600 file: {resolved} (mode={mode:04o})")
            with os.fdopen(descriptor, encoding="utf-8", closefd=False) as stream:
                value = stream.read().strip()
        finally:
            os.close(descriptor)
        if not value or "\n" in value or "\r" in value:
            raise error_type(f"{label} file must contain exactly one nonempty line: {resolved}")
        _cache[key] = _CacheEntry(value=value, checked_at=now)
        return value


def clear_secret_cache() -> None:
    """Clear process-local entries; primarily useful for deterministic tests."""
    with _cache_lock:
        _cache.clear()


__all__ = ["clear_secret_cache", "read_secret_file"]
