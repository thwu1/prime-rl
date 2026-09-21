from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest
from sandoq_provider.gateway import SandoqGatewayAdapter, SandoqHttpResponse, SandoqHttpTransportError
from sandoq_provider.pool import (
    AcquireWaiter,
    Assignment,
    PoolBroker,
    PoolClient,
    Slot,
    _AsyncUnixServer,
    _EventWriter,
    _PoolConnectionError,
)


def test_event_writer_close_flushes_pending_rows(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    writer = _EventWriter(path)
    rows = [json.dumps({"row": index}) + "\n" for index in range(512)]
    for row in rows:
        writer.append(row)

    writer.close()

    assert path.read_text().splitlines() == [row.rstrip("\n") for row in rows]
    assert writer.dropped == 0
    assert writer.stopped.is_set()

    writer.append(json.dumps({"row": "late"}) + "\n")
    assert writer.dropped == 1
    assert path.read_text().splitlines() == [row.rstrip("\n") for row in rows]


def test_event_writer_close_fails_if_shutdown_marker_cannot_be_queued(tmp_path) -> None:
    writer = object.__new__(_EventWriter)
    writer.path = tmp_path / "events.jsonl"
    writer.pending = queue.Queue(maxsize=1)
    writer.pending.put_nowait("occupied\n")
    writer.dropped = 0
    writer.state_lock = threading.Lock()
    writer.closing = threading.Event()
    writer.stopped = threading.Event()
    writer.thread = SimpleNamespace(is_alive=lambda: True, join=lambda timeout: None)

    with pytest.raises(TimeoutError, match="shutdown marker"):
        writer.close(timeout=0)

    assert writer.closing.is_set()


def _assigned_broker(*, releasing: bool) -> PoolBroker:
    broker = object.__new__(PoolBroker)
    broker.lock = threading.RLock()
    broker.changed = threading.Condition(broker.lock)
    broker._reconcile_event = threading.Event()
    broker.accepting = False
    broker.idle_slots = deque()
    broker.waiter_order = deque()
    broker.slots = [
        Slot(
            slot_id=0,
            state="recycling" if releasing else "assigned",
            outer_session_id="outer-1",
            exec_url="https://outer-1.example/",
            assignment_id="assignment-1",
            reuse_count=2,
        )
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
    broker.release_results = {}
    broker._event = lambda *args, **kwargs: None
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
    events: list[tuple[str, dict[str, object]]] = []
    broker._event = lambda event, **values: events.append((event, values))

    result = broker.cancel_acquire("client-1", "ticket-1")

    assert result == {"cancelled": True, "ticket_id": "ticket-1"}
    assert broker.slots[0].state == "idle"
    assert broker.slots[0].assignment_id is None
    assert broker.slots[0].reuse_count == 1
    assert list(broker.idle_slots) == [0]
    assert "assignment-1" not in broker.assignments
    assert "ticket-1" not in broker.waiters
    assert events == [
        (
            "assignment_cancelled",
            {
                "assignment_id": "assignment-1",
                "outer_session_id": "outer-1",
                "slot_id": 0,
                "generation": 0,
                "requested_image": "image",
                "cancellation_verified": True,
            },
        )
    ]


def test_assignment_acquired_records_authoritative_active_count() -> None:
    broker = object.__new__(PoolBroker)
    broker.lock = threading.RLock()
    broker.changed = threading.Condition(broker.lock)
    broker.accepting = True
    broker.idle_slots = deque((0, 1))
    broker.waiter_order = deque(("ticket-1", "ticket-2"))
    broker.waiters = {
        ticket_id: AcquireWaiter(
            ticket_id=ticket_id,
            client_id="client-1",
            requested_image="image",
            created_at=time.monotonic(),
            expires_at=time.monotonic() + 60,
        )
        for ticket_id in broker.waiter_order
    }
    broker.clients = {"client-1": time.monotonic()}
    broker.assignments = {}
    broker.slots = [
        Slot(
            slot_id=slot_id,
            state="idle",
            outer_session_id=f"outer-{slot_id}",
            exec_url=f"https://outer-{slot_id}.example/",
            reuse_threshold=6,
            created_at=time.time(),
        )
        for slot_id in range(2)
    ]
    broker.config = SimpleNamespace(
        bootstrap_workers=2,
        bootstrap_workers_per_image=2,
        max_reuse_count=6,
        managed_shell_recovery=True,
    )
    events: list[tuple[str, dict[str, object]]] = []
    broker._event = lambda event, **values: events.append((event, values))

    with broker.lock:
        broker._assign_waiters_locked()

    acquired = [values for event, values in events if event == "assignment_acquired"]
    assert [row["active_assignment_count"] for row in acquired] == [1, 2]
    assert len(broker.assignments) == 2


def test_release_publishes_terminal_event_before_marking_complete() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-1"
    broker.slots[0].outer_session_id = "outer-1"
    broker.config = SimpleNamespace(max_reuse_count=6, size=2, drain_timeout_s=1.0)
    broker.draining = False
    broker._delete_shell = lambda *args, **kwargs: None
    broker._outer_exec = lambda *args, **kwargs: SimpleNamespace(exit_code=0)
    broker._prune_images = lambda slot: None
    broker._append_idle_locked = lambda slot: setattr(slot, "state", "idle")
    observations: list[bool] = []
    broker._event = lambda event, **values: observations.append(
        event == "assignment_released" and values["assignment_id"] in broker.releasing_assignments
    )

    response = broker.release("client-1", "assignment-1")

    assert response["status"] == "recycled"
    assert observations == [True]
    assert broker.releasing_assignments == set()


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


def test_update_publishes_ready_event_under_assignment_lock() -> None:
    broker = _assigned_broker(releasing=False)
    observations: list[tuple[bool, bool]] = []
    broker._event = lambda event, **values: observations.append(
        (
            broker.lock._is_owned(),  # type: ignore[attr-defined]
            values["assignment_id"] in broker.assignments,
        )
    )
    broker._assign_waiters_locked = lambda: None

    broker.update("client-1", "assignment-1", {"ready": True})

    assert observations == [(True, True)]


def test_initial_shell_wal_is_long_kimi_only() -> None:
    standard = _assigned_broker(releasing=False)
    standard.config = SimpleNamespace(managed_shell_recovery=False)
    standard_wal: list[str] = []
    standard._wal_event = lambda event, **values: standard_wal.append(event)
    standard.update("client-1", "assignment-1", {"shell_id": "shell-standard"})

    long_kimi = _assigned_broker(releasing=False)
    long_kimi.config = SimpleNamespace(managed_shell_recovery=True)
    long_wal: list[tuple[str, dict[str, object]]] = []
    long_kimi._wal_event = lambda event, **values: long_wal.append((event, values))
    long_kimi.update("client-1", "assignment-1", {"shell_id": "shell-long"})

    assert standard_wal == []
    assert [event for event, _values in long_wal] == ["managed_shell_bound"]
    assert long_wal[0][1]["shell_generation"] == 0


def test_managed_shell_recovery_is_single_owner_and_durable() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
    )
    requests: list[tuple[str, str, object]] = []
    responses = iter(
        [
            SandoqHttpResponse(status_code=200, body={"status": "ok"}),
            SandoqHttpResponse(status_code=200, body={"shells": []}),
            SandoqHttpResponse(status_code=201, body={"shellId": "shell-new"}),
            SandoqHttpResponse(status_code=200, body={"exitCode": 0, "timedOut": False}),
        ]
    )

    def request_json(method: str, url: str, **kwargs: object) -> SandoqHttpResponse:
        requests.append((method, url, kwargs.get("body")))
        return next(responses)

    broker.gateway = SimpleNamespace(request_json=request_json)
    broker._auth_headers = lambda: {}
    wal: list[tuple[str, dict[str, object]]] = []
    events: list[tuple[str, dict[str, object]]] = []
    event_lock_state: list[tuple[bool, bool]] = []
    broker._wal_event = lambda event, **values: wal.append((event, values))

    def record_event(event: str, **values: object) -> None:
        events.append((event, values))
        event_lock_state.append((broker.lock._is_owned(), assignment.shell_recovering))  # type: ignore[attr-defined]

    broker._event = record_event

    recovered = broker.recover_managed_shell(
        "client-1",
        "assignment-1",
        "shell-old",
        workdir="/testbed",
    )
    duplicate = broker.recover_managed_shell(
        "client-1",
        "assignment-1",
        "shell-old",
        workdir="/testbed",
    )

    assert recovered == {"status": "recovered", "shell_id": "shell-new", "shell_generation": 1}
    assert duplicate == {"status": "already_recovered", "shell_id": "shell-new", "shell_generation": 1}
    assert assignment.shell_id == "shell-new"
    assert assignment.managed_shell_recovery_count == 1
    assert len(requests) == 4
    assert wal[0][0] == "managed_shell_recovered"
    assert events[0][0] == "managed_shell_recovered"
    assert event_lock_state == [(True, True)]


def test_managed_shell_can_recover_again_after_a_later_expiry() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-original"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
    )
    replacement_ids = iter(("shell-replacement-1", "shell-replacement-2"))

    def request_json(method: str, url: str, **kwargs: object) -> SandoqHttpResponse:
        del kwargs
        if method == "POST" and url.endswith("/v1/shells"):
            return SandoqHttpResponse(status_code=201, body={"shellId": next(replacement_ids)})
        return SandoqHttpResponse(
            status_code=200,
            body={"shells": []} if url.endswith("/v1/shells") else {"exitCode": 0, "timedOut": False},
        )

    broker.gateway = SimpleNamespace(request_json=request_json)
    broker._auth_headers = lambda: {}
    wal: list[tuple[str, dict[str, object]]] = []
    broker._wal_event = lambda event, **values: wal.append((event, values))
    broker._event = lambda *args, **kwargs: None

    first = broker.recover_managed_shell(
        "client-1",
        "assignment-1",
        "shell-original",
        workdir="/testbed",
    )
    second = broker.recover_managed_shell(
        "client-1",
        "assignment-1",
        str(first["shell_id"]),
        workdir="/testbed",
    )

    assert second == {
        "status": "recovered",
        "shell_id": "shell-replacement-2",
        "shell_generation": 2,
    }
    assert assignment.shell_generation == 2
    assert assignment.managed_shell_recovery_count == 2
    assert [values["shell_generation"] for event, values in wal if event == "managed_shell_recovered"] == [1, 2]


def test_managed_shell_recovery_requires_expected_shell_absent() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
    )
    responses = iter(
        [
            SandoqHttpResponse(status_code=200, body={"status": "ok"}),
            SandoqHttpResponse(status_code=200, body={"shells": [{"shellId": "shell-old"}]}),
        ]
    )
    broker.gateway = SimpleNamespace(request_json=lambda *args, **kwargs: next(responses))
    broker._auth_headers = lambda: {}
    broker._wal_event = lambda *args, **kwargs: None
    failure_event_state: list[tuple[str, bool, bool]] = []
    broker._event = lambda event, **kwargs: failure_event_state.append(
        (event, broker.lock._is_owned(), assignment.shell_recovering)  # type: ignore[attr-defined]
    )

    with pytest.raises(RuntimeError, match="managed shell recovery failed"):
        broker.recover_managed_shell(
            "client-1",
            "assignment-1",
            "shell-old",
            workdir="/testbed",
        )

    assert assignment.shell_id == "shell-old"
    assert assignment.managed_shell_failure_status == "managed_shell_recovery_failed"
    assert failure_event_state == [("managed_shell_recovery_failed", True, True)]


def test_shell_command_reservation_serializes_recovery() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        gateway_retry_attempts=1,
        gateway_retry_interval_s=0,
    )
    command_started = threading.Event()
    finish_command = threading.Event()

    def request_json(method: str, url: str, **kwargs: object) -> SandoqHttpResponse:
        del kwargs
        if method == "POST" and url.endswith("/v1/exec") and not command_started.is_set():
            command_started.set()
            assert finish_command.wait(timeout=1)
            return SandoqHttpResponse(status_code=200, body={"exitCode": 0, "timedOut": False})
        if method == "POST" and url.endswith("/v1/shells"):
            return SandoqHttpResponse(status_code=201, body={"shellId": "shell-new"})
        return SandoqHttpResponse(
            status_code=200,
            body={"shells": []} if url.endswith("/v1/shells") else {"exitCode": 0, "timedOut": False},
        )

    broker.gateway = SimpleNamespace(request_json=request_json)
    broker._auth_headers = lambda: {}
    broker._wal_event = lambda *args, **kwargs: None
    broker._event = lambda *args, **kwargs: None
    command_results: list[dict[str, object]] = []
    command_thread = threading.Thread(
        target=lambda: command_results.append(
            broker.managed_shell_request(
                "client-1",
                "assignment-1",
                "shell-old",
                body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
                request_timeout_seconds=10,
                admission_deadline_monotonic=time.monotonic() + 30,
            )
        )
    )
    command_thread.start()
    assert command_started.wait(timeout=1)
    recovered: list[dict[str, object]] = []

    thread = threading.Thread(
        target=lambda: recovered.append(
            broker.recover_managed_shell(
                "client-1",
                "assignment-1",
                "shell-old",
                workdir="/testbed",
            )
        )
    )
    thread.start()
    time.sleep(0.02)
    assert thread.is_alive()

    finish_command.set()
    command_thread.join(timeout=1)
    thread.join(timeout=1)

    assert not command_thread.is_alive()
    assert not thread.is_alive()
    assert command_results[0]["status"] == "response"
    assert recovered == [{"status": "recovered", "shell_id": "shell-new", "shell_generation": 1}]


def test_unknown_command_outcome_quarantines_and_blocks_a_second_command() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(managed_shell_recovery=True)
    broker._auth_headers = lambda: {}
    broker.gateway = SimpleNamespace(
        request_json=lambda *args, **kwargs: (_ for _ in ()).throw(
            SandoqHttpTransportError("POST", "TimeoutError", timed_out=True, delivery_state="unknown")
        )
    )

    first = broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
        request_timeout_seconds=10,
        admission_deadline_monotonic=time.monotonic() + 30,
    )
    second = broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
        request_timeout_seconds=10,
        admission_deadline_monotonic=time.monotonic() + 30,
    )

    assert first["status"] == "transport_error"
    assert first["delivery_state"] == "unknown"
    assert second == {
        "status": "terminal_failure",
        "failure_status": "managed_shell_command_outcome_unknown",
    }
    assert assignment.active_shell_operation is not None
    assert assignment.active_shell_operation_running is False
    assert assignment.managed_shell_failure_status == "managed_shell_command_outcome_unknown"
    assignment.active_shell_operation_deadline = time.monotonic() - 1
    events: list[str] = []
    broker._event = lambda event, **values: events.append(event)
    broker._expire_abandoned_shell_operations(time.monotonic())
    assert assignment.active_shell_operation is None
    assert assignment.managed_shell_failure_status == "managed_shell_command_outcome_unknown"
    assert events == ["managed_shell_operation_abandoned"]


def test_proven_not_sent_command_clears_reservation_for_safe_retry() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(managed_shell_recovery=True)
    broker._auth_headers = lambda: {}
    responses: list[object] = [
        SandoqHttpTransportError(
            "POST",
            "ClientConnectorError",
            timed_out=False,
            delivery_state="not_sent",
            retryable=True,
        ),
        SandoqHttpResponse(status_code=200, body={"exitCode": 0, "timedOut": False}),
    ]

    def request_json(*args: object, **kwargs: object) -> SandoqHttpResponse:
        del args, kwargs
        result = responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, SandoqHttpResponse)
        return result

    broker.gateway = SimpleNamespace(request_json=request_json)
    deadline = time.monotonic() + 30
    first = broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
        request_timeout_seconds=10,
        admission_deadline_monotonic=deadline,
    )
    second = broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
        request_timeout_seconds=10,
        admission_deadline_monotonic=deadline,
    )

    assert first["status"] == "transport_error"
    assert first["delivery_state"] == "not_sent"
    assert second["status"] == "response"
    assert assignment.active_shell_operation is None
    assert assignment.managed_shell_failure_status is None


@pytest.mark.parametrize("http_status", [408, 500, 502, 503, 504])
def test_ambiguous_http_response_keeps_quarantine(http_status: int) -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(managed_shell_recovery=True)
    broker._auth_headers = lambda: {}
    broker.gateway = SimpleNamespace(
        request_json=lambda *args, **kwargs: SandoqHttpResponse(status_code=http_status, body={})
    )

    response = broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
        request_timeout_seconds=10,
        admission_deadline_monotonic=time.monotonic() + 30,
    )

    assert response["status"] == "response"
    assert response["http_status"] == http_status
    assert assignment.active_shell_operation is not None
    assert assignment.active_shell_operation_running is False
    assert assignment.managed_shell_failure_status == "managed_shell_command_outcome_unknown"


@pytest.mark.parametrize("http_status", [404, 410])
def test_definitive_missing_shell_response_clears_reservation(http_status: int) -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(managed_shell_recovery=True)
    broker._auth_headers = lambda: {}
    broker.gateway = SimpleNamespace(
        request_json=lambda *args, **kwargs: SandoqHttpResponse(status_code=http_status, body={})
    )

    response = broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
        request_timeout_seconds=10,
        admission_deadline_monotonic=time.monotonic() + 30,
    )

    assert response["status"] == "response"
    assert response["http_status"] == http_status
    assert assignment.active_shell_operation is None
    assert assignment.active_shell_operation_running is False
    assert assignment.managed_shell_failure_status is None


def test_waiter_crossing_deadline_is_never_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    assignment.active_shell_operation = "shell-operation-existing"
    assignment.active_shell_operation_deadline = 200.0
    broker.config = SimpleNamespace(managed_shell_recovery=True)
    now = [100.0]
    monkeypatch.setattr("sandoq_provider.pool.time.monotonic", lambda: now[0])

    def release_after_deadline(*, timeout: float) -> None:
        assert timeout == 0.25
        assignment.active_shell_operation = None
        now[0] = 101.0

    monkeypatch.setattr(broker.changed, "wait", release_after_deadline)

    with pytest.raises(TimeoutError, match="admission timed out"):
        broker.managed_shell_request(
            "client-1",
            "assignment-1",
            "shell-old",
            body={"command": ["true"], "shellId": "shell-old", "timeout": 1},
            request_timeout_seconds=1,
            admission_deadline_monotonic=101.5,
        )

    assert assignment.active_shell_operation is None


def test_abandoned_shell_operation_expires_without_delete_race() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    assignment.active_shell_operation = "shell-operation-stale"
    assignment.active_shell_operation_deadline = time.monotonic() - 1
    events: list[tuple[str, bool]] = []
    broker._event = lambda event, **values: events.append(
        (event, broker.lock._is_owned())  # type: ignore[attr-defined]
    )

    broker._expire_abandoned_shell_operations(time.monotonic())

    assert assignment.active_shell_operation is None
    assert assignment.managed_shell_failure_status == "managed_shell_operation_abandoned"
    assert events == [("managed_shell_operation_abandoned", True)]


def test_running_shell_operation_is_never_expired_by_maintenance() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    assignment.active_shell_operation = "shell-operation-running"
    assignment.active_shell_operation_deadline = time.monotonic() - 1
    assignment.active_shell_operation_running = True
    events: list[str] = []
    broker._event = lambda event, **values: events.append(event)

    broker._expire_abandoned_shell_operations(time.monotonic())

    assert assignment.active_shell_operation == "shell-operation-running"
    assert assignment.active_shell_operation_running is True
    assert assignment.managed_shell_failure_status is None
    assert events == []


def test_gateway_refuses_command_if_full_budget_no_longer_fits_before_send() -> None:
    adapter = object.__new__(SandoqGatewayAdapter)
    requests = 0

    class Http:
        def request(self, *args: object, **kwargs: object) -> object:
            nonlocal requests
            del args, kwargs
            requests += 1
            raise AssertionError("expired command must not open an HTTP request")

    adapter._get_client = lambda: SimpleNamespace(http=Http())

    async def run() -> None:
        with pytest.raises(SandoqHttpTransportError) as raised:
            await adapter._request_json(
                "POST",
                "https://outer.example/v1/exec",
                {"command": ["true"], "shellId": "shell-old", "timeout": 5},
                {},
                10,
                time.monotonic() + 1,
            )
        assert raised.value.delivery_state == "not_sent"

    asyncio.run(run())
    assert requests == 0


def test_managed_shell_pool_request_never_uses_reconnecting_replay_path() -> None:
    client = object.__new__(PoolClient)
    client.client_id = "client-1"
    raw_calls = 0

    def raw_request(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal raw_calls
        del args, kwargs
        raw_calls += 1
        raise _PoolConnectionError("response lost")

    client._raw_request = raw_request
    client._request = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("non-idempotent command must not use reconnecting _request")
    )

    with pytest.raises(SandoqHttpTransportError) as raised:
        client.managed_shell_request(
            "assignment-1",
            "shell-old",
            body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
            request_timeout_seconds=10,
            admission_deadline_monotonic=time.monotonic() + 30,
        )

    assert raised.value.delivery_state == "unknown"
    assert raw_calls == 1


def test_managed_shell_pool_request_reconstructs_sanitized_results() -> None:
    client = object.__new__(PoolClient)
    client.client_id = "client-1"
    results = iter(
        [
            {
                "status": "response",
                "http_status": 404,
                "body": {},
            },
            {
                "status": "transport_error",
                "error_type": "ClientConnectorError",
                "timed_out": False,
                "delivery_state": "not_sent",
                "http_status": None,
                "retryable": True,
            },
        ]
    )
    client._raw_request = lambda *args, **kwargs: next(results)
    values = {
        "assignment_id": "assignment-1",
        "expected_shell_id": "shell-old",
        "body": {"command": ["true"], "shellId": "shell-old", "timeout": 5},
        "request_timeout_seconds": 10,
        "admission_deadline_monotonic": time.monotonic() + 30,
    }

    response = client.managed_shell_request(**values)
    assert response == SandoqHttpResponse(status_code=404, body={})
    with pytest.raises(SandoqHttpTransportError) as raised:
        client.managed_shell_request(**values)
    assert raised.value.error_type == "ClientConnectorError"
    assert raised.value.delivery_state == "not_sent"
    assert raised.value.retryable is True


def test_managed_shell_executor_saturation_does_not_starve_control_executor() -> None:
    broker = SimpleNamespace(config=SimpleNamespace(drain_workers=1, size=64, drain_timeout_s=1))
    server = _AsyncUnixServer(broker)
    gate = threading.Event()
    futures = [server.managed_shell_executor.submit(gate.wait) for _ in range(64)]
    try:
        assert server.managed_shell_executor._max_workers == 64
        assert server.executor.submit(lambda: "control").result(timeout=1) == "control"
    finally:
        gate.set()
        for future in futures:
            future.result(timeout=1)
        asyncio.run(server.close())


def test_release_waits_for_shell_command_reservation() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        drain_timeout_s=1.0,
        max_reuse_count=6,
        size=2,
    )
    broker.clients = {}
    broker.draining = False
    deleted: list[str] = []
    broker._delete_shell = lambda slot, shell_id, **kwargs: deleted.append(shell_id)
    broker._outer_exec = lambda *args, **kwargs: SimpleNamespace(exit_code=0)
    broker._prune_images = lambda slot: None
    broker._append_idle_locked = lambda slot: setattr(slot, "state", "idle")
    broker._event = lambda *args, **kwargs: None
    broker._auth_headers = lambda: {}
    command_started = threading.Event()
    finish_command = threading.Event()

    def request_json(*args: object, **kwargs: object) -> SandoqHttpResponse:
        del args, kwargs
        command_started.set()
        assert finish_command.wait(timeout=1)
        return SandoqHttpResponse(status_code=200, body={"exitCode": 0, "timedOut": False})

    broker.gateway = SimpleNamespace(request_json=request_json)
    command_thread = threading.Thread(
        target=lambda: broker.managed_shell_request(
            "client-1",
            "assignment-1",
            "shell-old",
            body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
            request_timeout_seconds=10,
            admission_deadline_monotonic=time.monotonic() + 30,
        )
    )
    command_thread.start()
    assert command_started.wait(timeout=1)
    released: list[dict[str, object]] = []
    thread = threading.Thread(target=lambda: released.append(broker.release("client-1", "assignment-1")))
    thread.start()
    time.sleep(0.02)

    assert thread.is_alive()
    assert deleted == []
    finish_command.set()
    command_thread.join(timeout=1)
    thread.join(timeout=1)

    assert not command_thread.is_alive()
    assert not thread.is_alive()
    assert deleted == ["shell-old"]
    assert released[0]["status"] == "recycled"


def test_release_never_deletes_while_broker_gateway_call_is_running() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    assignment.active_shell_operation = "shell-operation-running"
    assignment.active_shell_operation_deadline = time.monotonic() - 1
    assignment.active_shell_operation_running = True
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        drain_timeout_s=0.01,
        max_reuse_count=6,
        size=2,
    )
    broker.clients = {}
    broker.draining = False
    deleted: list[str] = []
    broker._delete_slot = lambda slot, reason: deleted.append(reason)
    broker._event = lambda *args, **kwargs: None

    with pytest.raises(TimeoutError, match="did not quiesce"):
        broker.release("client-1", "assignment-1")

    assert deleted == []
    assert assignment.active_shell_operation == "shell-operation-running"
    assert "assignment-1" in broker.assignments


def test_unknown_command_release_waits_for_quarantine_then_retires_outer() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        drain_timeout_s=1.0,
        max_reuse_count=6,
        size=2,
    )
    broker.clients = {}
    broker.draining = False
    broker._auth_headers = lambda: {}
    broker.gateway = SimpleNamespace(
        request_json=lambda *args, **kwargs: (_ for _ in ()).throw(
            SandoqHttpTransportError("POST", "TimeoutError", timed_out=True, delivery_state="unknown")
        )
    )
    deleted: list[str] = []
    broker._delete_slot = lambda slot, reason: (
        deleted.append(reason) or {"outer_session_id": "outer-1", "verified_http_status": 404}
    )
    broker._event = lambda *args, **kwargs: None

    broker.managed_shell_request(
        "client-1",
        "assignment-1",
        "shell-old",
        body={"command": ["true"], "shellId": "shell-old", "timeout": 1},
        request_timeout_seconds=2,
        admission_deadline_monotonic=time.monotonic() + 3,
    )
    released: list[dict[str, object]] = []
    release_thread = threading.Thread(target=lambda: released.append(broker.release("client-1", "assignment-1")))
    release_thread.start()
    time.sleep(0.02)
    assert release_thread.is_alive()
    assert deleted == []

    with broker.changed:
        assignment.active_shell_operation_deadline = time.monotonic() - 1
        broker.changed.notify_all()
    release_thread.join(timeout=1)

    assert not release_thread.is_alive()
    assert deleted == ["poisoned:managed_shell_lost"]
    assert released[0]["shell_failure_status"] == "managed_shell_command_outcome_unknown"
    assert released[0]["outer_deletion_verified_http_status"] == 404


def test_cancelled_worker_wait_does_not_release_broker_owned_gateway_call() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(managed_shell_recovery=True)
    broker._auth_headers = lambda: {}
    command_started = threading.Event()
    finish_command = threading.Event()

    def request_json(*args: object, **kwargs: object) -> SandoqHttpResponse:
        del args, kwargs
        command_started.set()
        assert finish_command.wait(timeout=2)
        return SandoqHttpResponse(status_code=200, body={"exitCode": 0, "timedOut": False})

    broker.gateway = SimpleNamespace(request_json=request_json)

    async def cancel_waiter() -> None:
        task = asyncio.create_task(
            asyncio.to_thread(
                broker.managed_shell_request,
                "client-1",
                "assignment-1",
                "shell-old",
                body={"command": ["true"], "shellId": "shell-old", "timeout": 5},
                request_timeout_seconds=10,
                admission_deadline_monotonic=time.monotonic() + 30,
            )
        )
        assert await asyncio.to_thread(command_started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert assignment.active_shell_operation is not None
        assert assignment.active_shell_operation_running is True
        finish_command.set()

    asyncio.run(cancel_waiter())
    deadline = time.monotonic() + 1
    while assignment.active_shell_operation is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert assignment.active_shell_operation is None
    assert assignment.active_shell_operation_running is False


@pytest.mark.parametrize(
    ("initial_failure", "expected_failure"),
    [
        (None, "managed_shell_operation_abandoned"),
        ("managed_shell_command_outcome_unknown", "managed_shell_command_outcome_unknown"),
    ],
)
def test_release_clears_stale_shell_reservation_and_retires_outer(
    initial_failure: str | None,
    expected_failure: str,
) -> None:
    broker = _assigned_broker(releasing=False)
    broker.clients = {}
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    assignment.active_shell_operation = "shell-operation-abandoned"
    assignment.active_shell_operation_deadline = time.monotonic() - 1
    assignment.managed_shell_failure_status = initial_failure
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        drain_timeout_s=1.0,
        max_reuse_count=6,
        size=2,
    )
    broker.draining = False
    deleted: list[str] = []
    broker._delete_slot = lambda slot, reason: (
        deleted.append(reason) or {"outer_session_id": "outer-1", "verified_http_status": 404}
    )
    broker._event = lambda *args, **kwargs: None

    released = broker.release(
        "client-1",
        "assignment-1",
        poison=True,
        reason="stale_client",
    )

    assert deleted == ["poisoned:managed_shell_lost"]
    assert released["status"] == "poisoned"
    assert released["shell_failure_status"] == expected_failure
    assert released["outer_deletion_verified_http_status"] == 404


def test_managed_shell_create_transport_failure_is_not_replayed() -> None:
    broker = _assigned_broker(releasing=False)
    assignment = broker.assignments["assignment-1"]
    assignment.shell_id = "shell-old"
    broker.config = SimpleNamespace(
        managed_shell_recovery=True,
        gateway_retry_attempts=15,
        gateway_retry_interval_s=0,
    )
    calls: list[tuple[str, str]] = []

    def request_json(method: str, url: str, **kwargs: object) -> SandoqHttpResponse:
        del kwargs
        calls.append((method, url.rsplit("/", 1)[-1]))
        if len(calls) == 3:
            raise RuntimeError("ambiguous create transport")
        return SandoqHttpResponse(
            status_code=200,
            body={"shells": []} if url.endswith("/v1/shells") else {"status": "ok"},
        )

    broker.gateway = SimpleNamespace(request_json=request_json)
    broker._auth_headers = lambda: {}
    broker._wal_event = lambda *args, **kwargs: None
    broker._event = lambda *args, **kwargs: None

    with pytest.raises(RuntimeError, match="managed shell recovery failed"):
        broker.recover_managed_shell(
            "client-1",
            "assignment-1",
            "shell-old",
            workdir="/testbed",
        )

    assert len(calls) == 3
    assert assignment.managed_shell_failure_status == "managed_shell_recovery_failed"


def test_ecr_credential_revalidates_assignment_before_event() -> None:
    broker = _assigned_broker(releasing=False)
    events: list[str] = []
    broker._event = lambda event, **values: events.append(event)

    def credential() -> dict[str, object]:
        with broker.lock:
            broker.assignments.clear()
        return {
            "source": "test",
            "generation": 1,
            "reused": False,
            "age_seconds": 0.0,
        }

    broker.ecr_credentials = {"registry.example": SimpleNamespace(get=credential)}

    with pytest.raises(RuntimeError, match="unknown pool assignment"):
        broker.ecr_credential("client-1", "assignment-1", "registry.example")

    assert events == []


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


def _empty_drain_broker(tmp_path, *, socket_path=None) -> PoolBroker:
    broker = object.__new__(PoolBroker)
    broker.lock = threading.RLock()
    broker.changed = threading.Condition(broker.lock)
    broker.config = SimpleNamespace(
        drain_timeout_s=0.1,
        drain_workers=1,
        socket_path=socket_path or tmp_path / "pool.sock",
    )
    broker.accepting = True
    broker.draining = False
    broker.waiter_order = deque()
    broker.waiters = {}
    broker.assignments = {}
    broker.releasing_assignments = set()
    broker.slots = []
    broker.drain_deletions = []
    broker.drain_failures = {}
    broker.active_creates = 0
    broker._reconcile_event = threading.Event()
    broker._maintenance_stop = threading.Event()
    broker._reconcile_thread = None
    broker._maintenance_thread = None
    broker.started = False
    broker._startup_stop = threading.Event()
    broker._startup_done = threading.Event()
    broker._event = lambda *args, **kwargs: None
    broker._event_writer = SimpleNamespace(close=lambda: None, dropped=0)
    broker._delete_executor = SimpleNamespace(shutdown=lambda **kwargs: None)
    broker._create_executor = SimpleNamespace(shutdown=lambda **kwargs: None)
    broker.gateway = SimpleNamespace(close=lambda: None)
    broker.stopped = threading.Event()
    return broker


def test_verified_drain_stops_when_gateway_close_fails(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    events: list[tuple[str, dict[str, object]]] = []
    closed: list[str] = []
    broker._event = lambda event, **values: events.append((event, values))
    broker._event_writer = SimpleNamespace(close=lambda: closed.append("events"))
    broker._delete_executor = SimpleNamespace(shutdown=lambda **kwargs: closed.append("delete_executor"))
    broker._create_executor = SimpleNamespace(shutdown=lambda **kwargs: closed.append("create_executor"))

    def fail_close() -> None:
        raise TimeoutError("telemetry exporter did not stop")

    broker.gateway = SimpleNamespace(close=fail_close)

    result = broker.drain("final_client_departure")

    assert result == {
        "drained": True,
        "deleted": [],
        "failures": {},
        "gateway_close_error_type": "TimeoutError",
    }
    assert broker.stopped.is_set()
    marker = json.loads((tmp_path / "pool.drained.json").read_text())
    assert marker["schema_version"] == 3
    assert marker["reason"] == "final_client_departure"
    assert marker["failures"] == {}
    assert marker["event_records_dropped"] == 0
    assert events[-1] == ("gateway_close_failed", {"error_type": "TimeoutError"})
    assert closed == ["delete_executor", "create_executor", "events"]


def test_drain_marker_failure_still_stops_and_closes_local_resources(tmp_path) -> None:
    missing_parent = tmp_path / "missing"
    broker = _empty_drain_broker(
        tmp_path,
        socket_path=missing_parent / "pool.sock",
    )
    closed: list[str] = []
    broker._event_writer = SimpleNamespace(close=lambda: closed.append("events"))
    broker._delete_executor = SimpleNamespace(shutdown=lambda **kwargs: closed.append("delete_executor"))
    broker._create_executor = SimpleNamespace(shutdown=lambda **kwargs: closed.append("create_executor"))
    broker.gateway = SimpleNamespace(close=lambda: closed.append("gateway"))

    with pytest.raises(FileNotFoundError):
        broker.drain("final_client_departure")

    assert broker.stopped.is_set()
    assert closed == ["delete_executor", "create_executor", "gateway", "events"]


def test_event_writer_close_failure_prevents_verified_drain_marker(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    broker._event_writer = SimpleNamespace(
        close=lambda: (_ for _ in ()).throw(TimeoutError("event writer timeout")),
        dropped=0,
    )

    with pytest.raises(RuntimeError, match="event log did not close cleanly"):
        broker.drain("final_client_departure")

    assert broker.stopped.is_set()
    assert not (tmp_path / "pool.drained.json").exists()


def test_drain_marker_records_dropped_event_count(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    broker._event_writer = SimpleNamespace(close=lambda: None, dropped=3)

    result = broker.drain("final_client_departure")

    assert result["drained"] is True
    marker = json.loads((tmp_path / "pool.drained.json").read_text())
    assert marker["event_records_dropped"] == 3


def test_drain_waits_for_terminal_release_event(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    broker.releasing_assignments = {"assignment-1"}
    events: list[str] = []
    broker._event = lambda event, **values: events.append(event)

    def finish_release() -> None:
        time.sleep(0.01)
        with broker.changed:
            broker._event("assignment_released", assignment_id="assignment-1")
            broker.releasing_assignments.clear()
            broker.changed.notify_all()

    release_thread = threading.Thread(target=finish_release)
    release_thread.start()
    result = broker.drain("final_client_departure")
    release_thread.join()

    assert result["drained"] is True
    assert events.index("assignment_released") < events.index("pool_drained")


def test_drain_rejects_a_blocked_maintenance_producer(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    started = threading.Event()
    unblock = threading.Event()

    def blocked_renewal() -> None:
        started.set()
        unblock.wait()
        broker._event("outer_renewed")

    maintenance_thread = threading.Thread(target=blocked_renewal)
    broker._maintenance_thread = maintenance_thread
    maintenance_thread.start()
    assert started.wait(timeout=1.0)

    result = broker.drain("final_client_departure")

    assert result["drained"] is False
    assert result["failures"] == {-2: "pool maintenance did not stop before the drain deadline"}
    assert not (tmp_path / "pool.drained.json").exists()
    unblock.set()
    maintenance_thread.join(timeout=1.0)


def test_drain_rejects_a_blocked_startup_producer(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    broker.started = True

    result = broker.drain("final_client_departure")

    assert broker._startup_stop.is_set()
    assert result["drained"] is False
    assert result["failures"] == {-3: "pool startup did not stop before the drain deadline"}
    assert not (tmp_path / "pool.drained.json").exists()


def test_start_after_drain_cannot_publish_or_start_producers(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    events: list[str] = []
    broker._event = lambda event, **values: events.append(event)

    result = broker.drain("final_client_departure")
    broker.start()

    assert result["drained"] is True
    assert events == ["pool_drained"]
    assert broker._startup_done.is_set()
    assert broker._reconcile_thread is None
    assert broker._maintenance_thread is None


def test_drain_omits_verified_noop_from_concurrent_delete(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    broker.slots = [Slot(slot_id=0, state="poisoned", outer_session_id="outer-1")]

    def already_deleted(slot, _reason, *, deadline=None):
        slot.outer_session_id = None
        return {"outer_session_id": None, "verified_http_status": 404}

    broker._delete_slot = already_deleted

    result = broker.drain("final_client_departure")

    assert result["drained"] is True
    assert result["deleted"] == []
    marker = json.loads((tmp_path / "pool.drained.json").read_text())
    assert marker["deleted"] == []


def test_drain_rejects_unverified_noop_from_concurrent_delete(tmp_path) -> None:
    broker = _empty_drain_broker(tmp_path)
    broker.slots = [Slot(slot_id=0, state="poisoned", outer_session_id="outer-1")]

    def unverified_noop(slot, _reason, *, deadline=None):
        slot.outer_session_id = None
        return {"outer_session_id": None, "verified_http_status": None}

    broker._delete_slot = unverified_noop

    result = broker.drain("final_client_departure")

    assert result["drained"] is False
    assert result["deleted"] == []
    assert result["failures"] == {0: "no-op outer deletion was not verified"}
    assert not (tmp_path / "pool.drained.json").exists()
