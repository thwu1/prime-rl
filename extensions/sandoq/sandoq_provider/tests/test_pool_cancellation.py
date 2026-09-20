from __future__ import annotations

import json
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest
from sandoq_provider.pool import AcquireWaiter, Assignment, PoolBroker, Slot


def _assigned_broker(*, releasing: bool) -> PoolBroker:
    broker = object.__new__(PoolBroker)
    broker.lock = threading.RLock()
    broker.changed = threading.Condition(broker.lock)
    broker._reconcile_event = threading.Event()
    broker.accepting = False
    broker.idle_slots = deque()
    broker.waiter_order = deque()
    broker.slots = [
        Slot(slot_id=0, state="recycling" if releasing else "assigned", assignment_id="assignment-1", reuse_count=2)
    ]
    broker.assignments = {
        "assignment-1": Assignment(
            assignment_id="assignment-1",
            client_id="client-1",
            slot_id=0,
            requested_image="image",
            acquired_at=0.0,
            ticket_id="ticket-1",
        )
    }
    broker.waiters = {
        "ticket-1": AcquireWaiter(
            ticket_id="ticket-1",
            client_id="client-1",
            requested_image="image",
            created_at=0.0,
            expires_at=1.0,
            response={"assignment_id": "assignment-1"},
        )
    }
    broker.releasing_assignments = {"assignment-1"} if releasing else set()
    return broker


def test_cancel_acquire_does_not_reclaim_an_assignment_during_release() -> None:
    broker = _assigned_broker(releasing=True)

    result = broker.cancel_acquire("client-1", "ticket-1")

    assert result == {"cancelled": False, "ticket_id": "ticket-1", "reason": "release_in_progress"}
    assert broker.slots[0].state == "recycling"
    assert broker.slots[0].assignment_id == "assignment-1"
    assert broker.slots[0].reuse_count == 2
    assert "assignment-1" in broker.assignments
    assert "ticket-1" in broker.waiters


def test_cancel_acquire_reclaims_an_unobserved_assignment() -> None:
    broker = _assigned_broker(releasing=False)

    result = broker.cancel_acquire("client-1", "ticket-1")

    assert result == {"cancelled": True, "ticket_id": "ticket-1"}
    assert broker.slots[0].state == "idle"
    assert broker.slots[0].assignment_id is None
    assert broker.slots[0].reuse_count == 1
    assert list(broker.idle_slots) == [0]
    assert "assignment-1" not in broker.assignments
    assert "ticket-1" not in broker.waiters


def test_update_tracks_task_and_auxiliary_images_for_cache_pruning() -> None:
    broker = _assigned_broker(releasing=False)

    result = broker.update(
        "client-1",
        "assignment-1",
        {
            "cached_images": ["task-image", "toolbox-image", "task-image"],
        },
    )

    assert result == {"updated": True}
    assert set(broker.slots[0].images) == {"task-image", "toolbox-image"}


def test_prune_images_shell_quotes_image_references() -> None:
    broker = object.__new__(PoolBroker)
    broker.config = SimpleNamespace(image_cache_max_entries=0)
    broker._storage_bytes = lambda slot: 0
    commands: list[str] = []
    broker._outer_exec = lambda slot, command, timeout: commands.append(command)
    slot = Slot(slot_id=0, images={"registry.example/repo:tag; echo unsafe": 0.0})

    broker._prune_images(slot)

    assert commands[0] == "podman image rm 'registry.example/repo:tag; echo unsafe' >/dev/null 2>&1 || true"


def _deletion_broker(slot: Slot) -> PoolBroker:
    broker = object.__new__(PoolBroker)
    broker.lock = threading.RLock()
    broker.changed = threading.Condition(broker.lock)
    broker.config = SimpleNamespace(drain_timeout_s=1.0)
    broker.slots = [slot]
    broker.clients = {"client-1": 0.0}
    broker.draining = False
    broker.drain_deletions = []
    broker._reconcile_event = threading.Event()
    broker._event = lambda *args, **kwargs: None
    broker._wal_event = lambda *args, **kwargs: None
    return broker


def test_poisoned_slot_delete_is_retried_and_replaced() -> None:
    slot = Slot(slot_id=0, state="poisoned", outer_session_id="outer-1")
    broker = _deletion_broker(slot)
    attempts = 0

    def delete_outer(session_id: str, *, deadline: float | None = None) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary delete failure")

    replacements: list[int] = []
    broker._delete_outer = delete_outer
    broker._start_create = lambda candidate: replacements.append(candidate.slot_id)

    with pytest.raises(RuntimeError, match="temporary delete failure"):
        broker._delete_slot(slot, "test")

    assert slot.state == "poisoned"
    assert slot.outer_session_id == "outer-1"
    assert slot.delete_failures == 1
    assert slot.next_delete_at > time.monotonic()

    broker._retry_poisoned_slot(slot)

    assert attempts == 2
    assert slot.state == "new"
    assert slot.outer_session_id is None
    assert slot.delete_failures == 0
    assert replacements == [0]


def test_schedule_poisoned_delete_claims_slot_once() -> None:
    slot = Slot(slot_id=0, state="poisoned", outer_session_id="outer-1", next_delete_at=0.0)
    broker = _deletion_broker(slot)
    submissions: list[tuple[object, Slot]] = []
    broker._delete_executor = SimpleNamespace(
        submit=lambda function, candidate: submissions.append((function, candidate))
    )

    broker._schedule_poisoned_deletes(time.monotonic())
    broker._schedule_poisoned_deletes(time.monotonic())

    assert slot.state == "delete_queued"
    assert len(submissions) == 1
    assert submissions[0][1] is slot


def test_recover_orphans_processes_futures_by_completion(tmp_path) -> None:
    wal_path = tmp_path / "pool.wal.jsonl"
    wal_path.write_text(
        "".join(
            json.dumps({"event": "outer_created", "outer_session_id": session_id}) + "\n"
            for session_id in ("outer-a", "outer-b")
        )
    )
    broker = object.__new__(PoolBroker)
    broker.config = SimpleNamespace(wal_path=wal_path, drain_timeout_s=0.05, drain_workers=2)
    broker.slots = []
    broker._wal_lock = threading.Lock()
    events: list[tuple[str, dict[str, object]]] = []
    broker._event = lambda event, **values: events.append((event, values))
    fast_delete_finished = threading.Event()

    def delete_outer(session_id: str, *, deadline: float | None = None) -> None:
        if session_id == "outer-b":
            fast_delete_finished.set()
            return
        assert fast_delete_finished.wait(timeout=1.0)
        time.sleep(0.1)
        raise RuntimeError("slow deletion failed")

    broker._delete_outer = delete_outer

    assert broker._recover_orphans() is False
    assert any(event == "outer_deleted" and values["outer_session_id"] == "outer-b" for event, values in events)
    assert any(event == "pool_recovery_incomplete" and values["remaining_orphans"] == 1 for event, values in events)


def test_created_slot_is_locked_until_wal_is_durable() -> None:
    slot = Slot(slot_id=0, state="creating", generation=1, request_id="request-1", reuse_threshold=4)
    broker = object.__new__(PoolBroker)
    broker.lock = threading.RLock()
    broker.changed = threading.Condition(broker.lock)
    broker.config = SimpleNamespace(environment="env", lease_duration="1h", create_deadline_s=60, max_reuse_count=4)
    broker.gateway = SimpleNamespace(
        create_session=lambda *args, **kwargs: SimpleNamespace(
            session_id="outer-1",
            port_urls={"exec": "https://exec.example/"},
            raw={},
        )
    )
    broker.draining = False
    broker.active_creates = 1
    broker._reconcile_event = threading.Event()
    broker._event = lambda *args, **kwargs: None
    broker._append_idle_locked = lambda candidate: setattr(candidate, "state", "idle")
    wal_observations: list[tuple[bool, str | None]] = []
    broker._wal_event = lambda *args, **kwargs: wal_observations.append(
        (broker.lock._is_owned(), slot.outer_session_id)  # type: ignore[attr-defined]
    )

    broker._create_slot(slot)

    assert wal_observations == [(True, "outer-1")]
    assert slot.state == "idle"
