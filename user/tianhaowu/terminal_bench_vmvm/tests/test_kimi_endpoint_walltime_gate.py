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
) -> bytes:
    return "".join(
        f"{10_000 + generation * 100 + index}|{state}|{restarts}|{elapsed_seconds}|10080\n"
        for index in range(gate.EXPECTED_ENDPOINTS)
    ).encode()


def _manifest() -> dict[str, object]:
    workers = [{"backend_sha256": _backend(f"worker-{index}")} for index in range(gate.EXPECTED_ENDPOINTS)]
    bundle = hashlib.sha256("".join(f"{worker['backend_sha256']}\n" for worker in workers).encode()).hexdigest()
    return {"workers": workers, "endpoint_bundle_sha256": bundle}


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
        serve_sh=serve_sh,
        runner=runner,
        now=lambda: "2026-09-24T12:00:00Z",
    )

    assert receipt["state"] == "passed"
    assert receipt["endpoint_count"] == 24
    assert receipt["all_running"] is True
    assert receipt["all_restarts_zero"] is True
    assert receipt["observed_minimum_remaining_seconds"] == 504_800
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
        )
        == receipt
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
        )["state"]
        == "passed"
    )

    value["observed_minimum_remaining_seconds"] -= 1
    with pytest.raises(gate.EndpointWalltimeGateError, match="endpoint_walltime_receipt_invalid"):
        gate.validate_receipt(
            value,
            manifest_sha256=manifest_sha256,
            endpoint_bundle_sha256=endpoint_bundle_sha256,
            profile=gate.EXTENDED_PROFILE,
            minimum_remaining_seconds=gate.EXTENDED_MINIMUM_REMAINING_SECONDS,
        )
    with pytest.raises(gate.EndpointWalltimeGateError, match="minimum_remaining_seconds_invalid"):
        gate.parse_scheduler_output(
            _scheduler(),
            [str(10_000 + index) for index in range(gate.EXPECTED_ENDPOINTS)],
            gate.EXTENDED_MINIMUM_REMAINING_SECONDS - 1,
        )


def test_direct_launcher_gates_only_explicit_extended_profile() -> None:
    launcher = Path(gate.__file__).with_name("run_direct_kimi_sandoq_stage.sh").read_text()
    capture = 'python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture'
    identity = 'python3 "$workflow_dir/eval_run_identity.py"'
    legacy_branch = 'if [[ "$endpoint_walltime_profile" == legacy ]]'
    extended_branch = 'elif [[ "$endpoint_walltime_profile" == tb4-extended-c24-two-wave-v1 ]]'
    config_read = 'tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))'
    assert "KIMI_ENDPOINT_WALLTIME_PROFILE:-legacy" in launcher
    assert launcher.index(legacy_branch) < launcher.index(extended_branch) < launcher.index(config_read)
    assert '"$eval_client_timeout" != 144000' in launcher
    assert '"$endpoint_minimum_remaining_seconds" -lt 324000' in launcher
    assert launcher.index(capture) < launcher.index(identity)
    assert 'python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" validate' in launcher
