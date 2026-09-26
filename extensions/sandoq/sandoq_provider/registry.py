"""Process-global registry mapping a sandoq ``sessionId`` to its connection info.

``ThreadedAsyncSandboxClient`` builds a *new* underlying client per worker thread,
so ``create()`` (thread A) and ``execute_command()`` (thread B) run on different
client instances. Session connection info must therefore live in a process-global,
lock-guarded table rather than on the client instance. This is safe because a
rollout's create/use/delete all happen within one env-server (worker) process.
"""

from __future__ import annotations

import contextvars
import copy
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionInfo:
    session_id: str
    exec_url: str  # always ends in "/"
    environment: str
    runtime_name: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    start_command: str | None = None
    lease_duration: str = "30m"
    start_replayed: bool = False
    port_urls: dict[str, str] = field(default_factory=dict)  # port name -> public URL (from lease response)
    outer_base_url: str | None = None
    source_image: str | None = None
    requested_image: str | None = None
    resolved_digest: str | None = None
    nested_ready: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
    readiness_started_at: float | None = None
    outer_session_id: str | None = None
    slot_id: int | None = None
    generation: int = 0
    reuse_count: int = 0
    shell_id: str | None = None
    shell_failure_status: str | None = None
    assignment_poisoned: bool = False
    assignment_poison_reason: str | None = None
    pool_wait_seconds: float = 0.0
    session_reuse: bool = False


_lock = threading.Lock()
_sessions: dict[str, SessionInfo] = {}
_cleanup_receipts: dict[str, dict[str, Any]] = {}
_task_context: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar(
    "sandoq_task_context",
    default=None,
)


def register(info: SessionInfo) -> None:
    with _lock:
        _sessions[info.session_id] = info


def get(session_id: str) -> SessionInfo | None:
    with _lock:
        return _sessions.get(session_id)


def unregister(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def all_ids() -> list[str]:
    with _lock:
        return list(_sessions.keys())


def bind_task_context(context: dict[str, object]) -> contextvars.Token:
    """Bind trusted per-task OCI fields across v1 runtime provisioning."""
    return _task_context.set(dict(context))


def reset_task_context(token: contextvars.Token) -> None:
    _task_context.reset(token)


def current_task_context() -> dict[str, object]:
    return dict(_task_context.get() or {})


def record_cleanup_receipt(runtime_name: str, receipt: dict[str, Any]) -> None:
    if not runtime_name:
        return
    with _lock:
        _cleanup_receipts[runtime_name] = copy.deepcopy(receipt)


def get_cleanup_receipt(runtime_name: str) -> dict[str, Any] | None:
    with _lock:
        receipt = _cleanup_receipts.get(runtime_name)
        return copy.deepcopy(receipt) if receipt is not None else None


def pop_cleanup_receipt(runtime_name: str) -> dict[str, Any] | None:
    with _lock:
        receipt = _cleanup_receipts.pop(runtime_name, None)
        return copy.deepcopy(receipt) if receipt is not None else None


def clear_cleanup_receipts() -> None:
    with _lock:
        _cleanup_receipts.clear()
