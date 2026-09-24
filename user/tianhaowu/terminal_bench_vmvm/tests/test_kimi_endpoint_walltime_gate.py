from __future__ import annotations

import hashlib
import json
from pathlib import Path

import direct_kimi_workers
import kimi_endpoint_walltime_gate as gate
import pytest
from inference_route_generation import canonical_backend_identifier


def _backend(host: str, port: int = 8000) -> str:
    return canonical_backend_identifier(f"http://{host}:{port}/v1").removeprefix("backend-sha256:")


def _status(*, generation: int = 0, changed_route: bool = False, metadata_tick: int = 0) -> bytes:
    endpoints = []
    for index in range(gate.EXPECTED_ENDPOINTS):
        host = f"worker-{index}"
        if changed_route and index == gate.EXPECTED_ENDPOINTS - 1:
            host = "rotated-worker"
        endpoints.append(
            {
                "jobid": str(10_000 + generation * 100 + index),
                "host": host,
                "port": 8000,
                "slurm_state": "RUNNING",
                "sub_state": "ready",
            }
        )
    return (
        json.dumps(
            {
                "schema_version": 4,
                "deployment_id": gate.EXPECTED_DEPLOYMENT,
                "phase": "serving",
                "endpoints_summary": {
                    "desired": gate.EXPECTED_ENDPOINTS,
                    "ready": gate.EXPECTED_ENDPOINTS,
                    "running_not_ready": 0,
                    "pending": 0,
                },
                "endpoints": endpoints,
                "untrusted_extra_status_field": metadata_tick,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _scheduler(
    *,
    generation: int = 0,
    state: str = "RUNNING",
    restarts: int = 0,
    elapsed_seconds: int = 100_000,
    indexes: range = range(gate.EXPECTED_ENDPOINTS),
) -> bytes:
    return "".join(
        f"{10_000 + generation * 100 + index}|{state}|{restarts}|{elapsed_seconds}|10080\n"
        for index in indexes
    ).encode()


def _manifest() -> dict[str, object]:
    workers = [{"backend_sha256": _backend(f"worker-{index}")} for index in range(gate.EXPECTED_ENDPOINTS)]
    bundle = hashlib.sha256("".join(f"{worker['backend_sha256']}\n" for worker in workers).encode()).hexdigest()
    return {
        "schema_version": 1,
        "workers": workers,
        "endpoint_bundle_sha256": bundle,
        "router": {
            "max_concurrent_requests": 24,
            "queue_size": 24,
            "request_timeout_seconds": 144_000,
            "queue_timeout_seconds": 144_000,
            "retries": 0,
        },
    }


def _c23_manifest(*, excluded_index: int = 0) -> dict[str, object]:
    all_workers = [
        {
            "backend_sha256": _backend(f"worker-{index}"),
            "model_sha256": hashlib.sha256(b"Kimi-K3").hexdigest(),
        }
        for index in range(gate.EXPECTED_ENDPOINTS)
    ]
    all_workers.sort(key=lambda worker: worker["backend_sha256"])
    excluded_worker = next(
        worker for worker in all_workers if worker["backend_sha256"] == _backend(f"worker-{excluded_index}")
    )
    selected_workers = [worker for worker in all_workers if worker != excluded_worker]
    selected_bundle = gate._bundle_sha256([worker["backend_sha256"] for worker in selected_workers])
    source_bundle = gate._bundle_sha256([worker["backend_sha256"] for worker in all_workers])
    return {
        "schema_version": 4,
        "selection_profile": gate.C23_MANIFEST_SELECTION_PROFILE,
        "source_endpoint_bundle_sha256": source_bundle,
        "endpoint_bundle_sha256": selected_bundle,
        "excluded_worker": excluded_worker,
        "workers": selected_workers,
        "router": {
            "capacity_profile": gate.C23_MANIFEST_CAPACITY_PROFILE,
            "max_concurrent_requests": gate.C23_SELECTED_ENDPOINTS,
            "queue_size": gate.C23_SELECTED_ENDPOINTS,
            "request_timeout_seconds": gate.EXTENDED_REQUEST_TIMEOUT_SECONDS,
            "queue_timeout_seconds": gate.EXTENDED_REQUEST_TIMEOUT_SECONDS,
            "retries": 0,
        },
    }


def test_capture_gate_accepts_exact_stable_24_job_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)
    tmp_path.chmod(0o700)
    serve_sh = tmp_path / "serve.sh"
    serve_sh.write_text("#!/bin/sh\n")
    calls: list[tuple[str, ...]] = []
    status_calls = 0

    def runner(argv, _timeout):
        nonlocal status_calls
        calls.append(tuple(argv))
        if argv[0] == str(gate.SACCT):
            return gate.CommandResult(0, _scheduler())
        status_calls += 1
        # The raw snapshots may differ in unrelated coordinator metadata, but
        # their endpoint/job generation must remain identical.
        return gate.CommandResult(0, _status(metadata_tick=status_calls))

    output = tmp_path / "endpoint-walltime.json"
    receipt = gate.capture_gate(
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        output=output,
        profile=gate.EXTENDED_PROFILE,
        minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        task_count=25,
        serve_sh=serve_sh,
        runner=runner,
        now=lambda: "2026-09-24T12:00:00Z",
    )

    assert receipt["state"] == "passed"
    assert receipt["endpoint_count"] == 24
    assert receipt["all_running"] is True
    assert receipt["all_restarts_zero"] is True
    assert receipt["observed_minimum_remaining_seconds"] == 504_800
    assert receipt["task_count"] == 25
    assert receipt["status_snapshot_before_sha256"] != receipt["status_snapshot_after_sha256"]
    assert output.stat().st_mode & 0o777 == 0o600
    raw_receipt = output.read_text()
    assert "10000" not in raw_receipt
    assert len(calls) == 3
    assert calls[1][0] == str(gate.SACCT)
    assert calls[1][1:3] == ("-M", gate.EXPECTED_CLUSTER)
    assert all("srun" not in command and "sbatch" not in command for call in calls for command in call)
    assert (
        gate.load_receipt(
            output,
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=manifest["endpoint_bundle_sha256"],
            profile=gate.EXTENDED_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
        )
        == receipt
    )


def test_c23_capture_requires_full_24_status_and_schedules_only_selected_23(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    excluded_index = 0
    manifest = _c23_manifest(excluded_index=excluded_index)
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)
    tmp_path.chmod(0o700)
    serve_sh = tmp_path / "serve.sh"
    serve_sh.write_text("#!/bin/sh\n")
    calls: list[tuple[str, ...]] = []

    def runner(argv, _timeout):
        calls.append(tuple(argv))
        if argv[0] == str(gate.SACCT):
            selected_job_ids = argv[argv.index("-j") + 1].split(",")
            assert str(10_000 + excluded_index) not in selected_job_ids
            assert len(selected_job_ids) == gate.C23_SELECTED_ENDPOINTS
            selected_indexes = range(1, gate.EXPECTED_ENDPOINTS)
            return gate.CommandResult(0, _scheduler(indexes=selected_indexes))
        return gate.CommandResult(0, _status())

    output = tmp_path / "endpoint-walltime-c23.json"
    receipt = gate.capture_gate(
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        output=output,
        profile=gate.C23_PROFILE,
        minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        task_count=25,
        serve_sh=serve_sh,
        runner=runner,
        now=lambda: "2026-09-24T12:00:00Z",
    )

    excluded_backend = _backend("worker-0")
    excluded_job_sha256 = hashlib.sha256(b"10000\n").hexdigest()
    assert receipt["schema_version"] == gate.C23_RECEIPT_SCHEMA_VERSION
    assert receipt["endpoint_count"] == gate.C23_SELECTED_ENDPOINTS
    assert receipt["live_endpoint_count"] == gate.EXPECTED_ENDPOINTS
    assert receipt["excluded_endpoint_count"] == 1
    assert receipt["endpoint_bundle_sha256"] == manifest["endpoint_bundle_sha256"]
    assert receipt["source_endpoint_bundle_sha256"] == manifest["source_endpoint_bundle_sha256"]
    assert receipt["excluded_backend_sha256"] == excluded_backend
    assert receipt["excluded_endpoint_job_sha256"] == excluded_job_sha256
    assert receipt["status_snapshot_before_sha256"] == hashlib.sha256(_status()).hexdigest()
    assert receipt["status_snapshot_after_sha256"] == hashlib.sha256(_status()).hexdigest()
    full_generation = "".join(
        f"{10_000 + index}|{_backend(f'worker-{index}')}\n" for index in range(gate.EXPECTED_ENDPOINTS)
    ).encode()
    assert receipt["full_endpoint_generation_sha256"] == hashlib.sha256(full_generation).hexdigest()
    assert receipt["excluded_endpoint_binding_sha256"] == hashlib.sha256(
        f"{excluded_job_sha256}|{excluded_backend}\n".encode()
    ).hexdigest()
    assert "10000" not in output.read_text()
    assert len(calls) == 3
    assert (
        gate.load_receipt(
            output,
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=manifest["endpoint_bundle_sha256"],
            profile=gate.C23_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
            source_endpoint_bundle_sha256=manifest["source_endpoint_bundle_sha256"],
            excluded_backend_sha256=excluded_backend,
        )
        == receipt
    )


def test_c23_capture_rejects_live_deployment_that_is_not_24_of_24_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _c23_manifest()
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)
    tmp_path.chmod(0o700)
    serve_sh = tmp_path / "serve.sh"
    serve_sh.write_text("#!/bin/sh\n")
    status = json.loads(_status())
    status["endpoints_summary"]["ready"] = gate.EXPECTED_ENDPOINTS - 1
    status["endpoints_summary"]["running_not_ready"] = 1
    calls = 0

    def runner(_argv, _timeout):
        nonlocal calls
        calls += 1
        return gate.CommandResult(0, json.dumps(status).encode())

    with pytest.raises(gate.EndpointWalltimeGateError, match="deployment_status_not_exactly_ready"):
        gate.capture_gate(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            output=tmp_path / "receipt.json",
            profile=gate.C23_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
            serve_sh=serve_sh,
            runner=runner,
        )
    assert calls == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "source_bundle",
        "selected_bundle",
        "excluded_overlap",
        "selected_count",
        "capacity_profile",
    ],
)
def test_c23_manifest_selection_contract_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    manifest = _c23_manifest()
    if mutation == "source_bundle":
        manifest["source_endpoint_bundle_sha256"] = "f" * 64
    elif mutation == "selected_bundle":
        manifest["endpoint_bundle_sha256"] = "f" * 64
    elif mutation == "excluded_overlap":
        manifest["excluded_worker"] = manifest["workers"][0]
    elif mutation == "selected_count":
        manifest["workers"] = manifest["workers"][:-1]
    else:
        manifest["router"]["capacity_profile"] = "wrong"
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)

    with pytest.raises(gate.EndpointWalltimeGateError, match="extended_router_manifest_invalid"):
        gate._load_manifest(manifest_path, manifest_sha256, profile=gate.C23_PROFILE)


def test_c23_scheduler_rejects_full_fleet_or_short_selected_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _c23_manifest()
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)
    tmp_path.chmod(0o700)
    serve_sh = tmp_path / "serve.sh"
    serve_sh.write_text("#!/bin/sh\n")

    def runner(argv, _timeout):
        if argv[0] == str(gate.SACCT):
            # A full-fleet scheduler snapshot cannot substitute for exact
            # evidence about only the manifest-selected worker set.
            return gate.CommandResult(0, _scheduler())
        return gate.CommandResult(0, _status())

    with pytest.raises(gate.EndpointWalltimeGateError, match="scheduler_endpoint_job_set_mismatch"):
        gate.capture_gate(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            output=tmp_path / "receipt.json",
            profile=gate.C23_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
            serve_sh=serve_sh,
            runner=runner,
        )

    selected_job_ids = [str(10_000 + index) for index in range(1, gate.EXPECTED_ENDPOINTS)]
    with pytest.raises(gate.EndpointWalltimeGateError, match="scheduler_endpoint_walltime_insufficient"):
        gate.parse_scheduler_output(
            _scheduler(indexes=range(1, gate.EXPECTED_ENDPOINTS), elapsed_seconds=300_001),
            selected_job_ids,
            gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            expected_endpoint_count=gate.C23_SELECTED_ENDPOINTS,
        )


def test_c23_receipt_binds_exclusion_and_full_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _c23_manifest()
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)
    tmp_path.chmod(0o700)
    serve_sh = tmp_path / "serve.sh"
    serve_sh.write_text("#!/bin/sh\n")

    def runner(argv, _timeout):
        if argv[0] == str(gate.SACCT):
            return gate.CommandResult(0, _scheduler(indexes=range(1, gate.EXPECTED_ENDPOINTS)))
        return gate.CommandResult(0, _status())

    receipt = gate.capture_gate(
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        output=tmp_path / "receipt.json",
        profile=gate.C23_PROFILE,
        minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        task_count=25,
        serve_sh=serve_sh,
        runner=runner,
        now=lambda: "2026-09-24T12:00:00Z",
    )
    excluded_backend = manifest["excluded_worker"]["backend_sha256"]

    for field in (
        "source_endpoint_bundle_sha256",
        "full_endpoint_jobs_sha256",
        "full_endpoint_generation_sha256",
        "excluded_endpoint_job_sha256",
        "excluded_backend_sha256",
        "excluded_endpoint_binding_sha256",
    ):
        tampered = dict(receipt)
        tampered[field] = "f" * 64
        with pytest.raises(gate.EndpointWalltimeGateError, match="endpoint_walltime_receipt_invalid"):
            gate.validate_receipt(
                tampered,
                manifest_sha256=manifest_sha256,
                endpoint_bundle_sha256=manifest["endpoint_bundle_sha256"],
                profile=gate.C23_PROFILE,
                minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
                task_count=25,
                source_endpoint_bundle_sha256=manifest["source_endpoint_bundle_sha256"],
                excluded_backend_sha256=excluded_backend,
            )

    # Even a self-consistent rehash cannot substitute a different manifest
    # source bundle or excluded backend supplied by the caller.
    for field in ("source_endpoint_bundle_sha256", "excluded_backend_sha256"):
        tampered = dict(receipt)
        tampered[field] = "f" * 64
        if field == "excluded_backend_sha256":
            tampered["excluded_endpoint_binding_sha256"] = hashlib.sha256(
                f"{tampered['excluded_endpoint_job_sha256']}|{tampered[field]}\n".encode()
            ).hexdigest()
        unsigned = dict(tampered)
        unsigned.pop("receipt_sha256")
        tampered["receipt_sha256"] = hashlib.sha256(gate._canonical_json(unsigned)).hexdigest()
        with pytest.raises(gate.EndpointWalltimeGateError, match="endpoint_walltime_receipt_invalid"):
            gate.validate_receipt(
                tampered,
                manifest_sha256=manifest_sha256,
                endpoint_bundle_sha256=manifest["endpoint_bundle_sha256"],
                profile=gate.C23_PROFILE,
                minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
                task_count=25,
                source_endpoint_bundle_sha256=manifest["source_endpoint_bundle_sha256"],
                excluded_backend_sha256=excluded_backend,
            )


@pytest.mark.parametrize(
    ("scheduler", "reason"),
    [
        (_scheduler(state="PENDING"), "scheduler_endpoint_not_running"),
        (_scheduler(restarts=1), "scheduler_endpoint_restarted"),
        (_scheduler(elapsed_seconds=300_001), "scheduler_endpoint_walltime_insufficient"),
        (_scheduler()[:-1].rsplit(b"\n", 1)[0] + b"\n", "scheduler_endpoint_job_set_mismatch"),
    ],
)
def test_scheduler_gate_fails_closed(scheduler: bytes, reason: str) -> None:
    job_ids = [str(10_000 + index) for index in range(gate.EXPECTED_ENDPOINTS)]
    with pytest.raises(gate.EndpointWalltimeGateError, match=reason):
        gate.parse_scheduler_output(
            scheduler,
            job_ids,
            gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        )


def test_status_snapshot_must_match_direct_worker_bundle() -> None:
    expected = [_backend(f"worker-{index}") for index in range(gate.EXPECTED_ENDPOINTS)]
    expected[-1] = "f" * 64
    with pytest.raises(gate.EndpointWalltimeGateError, match="deployment_endpoint_bundle_mismatch"):
        gate.parse_status_snapshot(_status(), expected)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_seconds", 43_200),
        ("max_concurrent_requests", 64),
        ("queue_size", 64),
        ("queue_timeout_seconds", 43_200),
        ("retries", 1),
        ("capacity_profile", "sandoq-c64-w2-v1"),
    ],
)
def test_gate_rejects_non_extended_router_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    manifest = _manifest()
    manifest["router"][field] = value
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)

    with pytest.raises(gate.EndpointWalltimeGateError, match="extended_router_manifest_invalid"):
        gate._load_manifest(manifest_path, manifest_sha256)


def test_status_rotation_between_scheduler_reads_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    monkeypatch.setattr(direct_kimi_workers, "validate_saved_manifest", lambda *_args, **_kwargs: manifest)
    tmp_path.chmod(0o700)
    serve_sh = tmp_path / "serve.sh"
    serve_sh.write_text("#!/bin/sh\n")
    status_calls = 0

    def runner(argv, _timeout):
        nonlocal status_calls
        if argv[0] == str(gate.SACCT):
            return gate.CommandResult(0, _scheduler())
        status_calls += 1
        return gate.CommandResult(0, _status(generation=0 if status_calls == 1 else 1))

    with pytest.raises(gate.EndpointWalltimeGateError, match="deployment_endpoint_generation_changed"):
        gate.capture_gate(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            output=tmp_path / "receipt.json",
            profile=gate.EXTENDED_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
            serve_sh=serve_sh,
            runner=runner,
        )


def test_receipt_digest_and_90_hour_floor_are_fail_closed() -> None:
    manifest_sha256 = "a" * 64
    endpoint_bundle_sha256 = "b" * 64
    value = {
        "schema_version": 1,
        "kind": gate.RECEIPT_KIND,
        "state": "passed",
        "profile": gate.EXTENDED_PROFILE,
        "checked_at": "2026-09-24T12:00:00Z",
        "deployment": gate.EXPECTED_DEPLOYMENT,
        "cluster": gate.EXPECTED_CLUSTER,
        "endpoint_count": 24,
        "all_running": True,
        "all_restarts_zero": True,
        "minimum_remaining_seconds": gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        "observed_minimum_remaining_seconds": gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        "task_count": 25,
        "direct_worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
        "endpoint_jobs_sha256": "c" * 64,
        "endpoint_generation_sha256": "d" * 64,
        "status_snapshot_before_sha256": "e" * 64,
        "status_snapshot_after_sha256": "f" * 64,
        "scheduler_observation_sha256": "1" * 64,
    }
    value["receipt_sha256"] = hashlib.sha256(gate._canonical_json(value)).hexdigest()
    assert (
        gate.validate_receipt(
            value,
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=endpoint_bundle_sha256,
            profile=gate.EXTENDED_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
        )["state"]
        == "passed"
    )

    value["observed_minimum_remaining_seconds"] -= 1
    unsigned = dict(value)
    unsigned.pop("receipt_sha256")
    value["receipt_sha256"] = hashlib.sha256(gate._canonical_json(unsigned)).hexdigest()
    with pytest.raises(gate.EndpointWalltimeGateError, match="endpoint_walltime_receipt_invalid"):
        gate.validate_receipt(
            value,
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=endpoint_bundle_sha256,
            profile=gate.EXTENDED_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
        )

    value["observed_minimum_remaining_seconds"] = gate.EXTENDED_MINIMUM_REMAINING_SECONDS
    value["task_count"] = 26
    unsigned = dict(value)
    unsigned.pop("receipt_sha256")
    value["receipt_sha256"] = hashlib.sha256(gate._canonical_json(unsigned)).hexdigest()
    with pytest.raises(gate.EndpointWalltimeGateError, match="endpoint_walltime_receipt_invalid"):
        gate.validate_receipt(
            value,
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=endpoint_bundle_sha256,
            profile=gate.EXTENDED_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
            task_count=25,
        )
    with pytest.raises(gate.EndpointWalltimeGateError, match="minimum_remaining_seconds_invalid"):
        gate.parse_scheduler_output(
            _scheduler(),
            [str(10_000 + index) for index in range(gate.EXPECTED_ENDPOINTS)],
            gate.EXTENDED_MINIMUM_REMAINING_SECONDS - 1,
        )


@pytest.mark.parametrize("task_count", [0, 24, 49, 66])
def test_extended_profile_rejects_non_two_wave_task_counts(task_count: int) -> None:
    with pytest.raises(gate.EndpointWalltimeGateError, match="extended_two_wave_task_count_invalid"):
        gate._validate_task_count(task_count)


@pytest.mark.parametrize("task_count", [0, 24, 47, 48, 66])
def test_c23_profile_rejects_non_two_wave_task_counts(task_count: int) -> None:
    with pytest.raises(gate.EndpointWalltimeGateError, match="extended_two_wave_task_count_invalid"):
        gate._validate_task_count(task_count, profile=gate.C23_PROFILE)


@pytest.mark.parametrize("task_count", [25, 46])
def test_c23_profile_accepts_bounded_two_wave_task_counts(task_count: int) -> None:
    gate._validate_task_count(task_count, profile=gate.C23_PROFILE)


def test_direct_launcher_gates_only_explicit_extended_profile() -> None:
    launcher = Path(gate.__file__).with_name("run_direct_kimi_sandoq_stage.sh").read_text()
    capture = 'python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture'
    identity = 'python3 "$workflow_dir/eval_run_identity.py"'
    assert "KIMI_ENDPOINT_WALLTIME_PROFILE:-legacy" in launcher
    assert 'if [[ "$direct_request_timeout" == 144000 ]]' in launcher
    assert "expected_walltime_profile=tb4-extended-c24-two-wave-v1" in launcher
    assert "expected_walltime_profile=tb4-c23-v1" in launcher
    assert '"$endpoint_walltime_profile" != "$expected_walltime_profile"' in launcher
    assert 'elif [[ "$endpoint_walltime_profile" != legacy' in launcher
    assert '"$approved_task_count" -le "$expected_router_concurrency"' in launcher
    assert '"$approved_task_count" -gt "$maximum_two_wave_tasks"' in launcher
    assert '"$endpoint_minimum_remaining_seconds" -lt 324000' in launcher
    assert launcher.index(capture) < launcher.index(identity)
    assert 'python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" validate' in launcher
