from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import terminal_bench_vmvm.offline_verifier_catalog_materializer as materializer_module
from terminal_bench_vmvm.offline_verifier_catalog import (
    CatalogIdentity,
    ExpectedTaskBinding,
    OfflineCatalogError,
    OfflineVerifierCatalog,
    RuntimeFingerprint,
    binding_plan_sha256,
    catalog_consumer_code_sha256,
    closure_sha256,
)
from terminal_bench_vmvm.offline_verifier_catalog_materializer import (
    MaterializationPlan,
    WorkerPolicy,
    WorkerResponse,
    WorkerRunner,
    _bounded_map,
    _directory_identity,
    _drain_task,
    _ExclusiveFileLock,
    _open_absolute_nofollow,
    _parse_probe_result,
    _parse_recovery_result,
    _process_start_ticks,
    _recovery_request,
    _rename_noreplace,
    _rename_noreplace_at,
    _revalidate_named_directory,
    _rotation_audit_record,
    _seal_and_fsync_directory_tree,
    materialization_plan_payload,
    materialize_catalog,
    materializer_controller_code_sha256,
    worker_environment_sha256,
    worker_recovery_scope_sha256,
)
from terminal_bench_vmvm.source_wheels import canonical_json, inspect_wheelhouse, pack_wheelhouse


def _digest(value: str | bytes) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _allowlist_digest(kind: str, values: list[str]) -> str:
    return _digest(canonical_json({"schema_version": 1, "kind": kind, "values": values}))


def _wheel(distribution: str, version: str) -> bytes:
    wheel_distribution = distribution.replace("-", "_")
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        metadata_dir = f"{wheel_distribution}-{version}.dist-info"
        wheel.writestr(
            f"{metadata_dir}/METADATA",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n",
        )
        wheel.writestr(
            f"{metadata_dir}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: materializer-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return output.getvalue()


def _private_directory(path: Path) -> Path:
    path.mkdir()
    path.chmod(0o700)
    return path


def _write_private(path: Path, payload: bytes, mode: int = 0o400) -> None:
    path.write_bytes(payload)
    path.chmod(mode)


def _rotation_metadata(token: Path, rotator_sha256: str, generation: int) -> bytes:
    status = token.stat()
    now = int(time.time())
    return canonical_json(
        {
            "schema_version": 1,
            "generation": generation,
            "issued_at_unix": now - 60,
            "heartbeat_at_unix": now,
            "expires_at_unix": now + 3600,
            "rotator_sha256": rotator_sha256,
            "token_file": {
                "path_sha256": _digest(str(token)),
                "device": status.st_dev,
                "inode": status.st_ino,
                "owner": status.st_uid,
                "mode": stat.S_IMODE(status.st_mode),
                "links": status.st_nlink,
                "size": status.st_size,
                "modified_ns": status.st_mtime_ns,
                "changed_ns": status.st_ctime_ns,
            },
        }
    )


def _worker_script(
    fixture_path: Path,
    *,
    bad_cleanup: bool,
    bad_validation: bool,
    exit_after_response: bool,
    hang_after_response: bool,
) -> str:
    return (
        r"""#!__PYTHON__
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

parser = argparse.ArgumentParser()
parser.add_argument("--request", type=Path, required=True)
parser.add_argument("--request-sha256", required=True)
parser.add_argument("--response", type=Path, required=True)
parser.add_argument("--artifact-dir", type=Path, required=True)
args = parser.parse_args()
request_payload = args.request.read_bytes()
if hashlib.sha256(request_payload).hexdigest() != args.request_sha256:
    raise SystemExit(2)
request = json.loads(request_payload)
fixture = json.loads(Path(__FIXTURE_PATH__).read_text())
operation = request["operation"]
if operation == "recover":
    result = {
        "durable_provider_wal": True,
        "recovery_attempted": True,
        "remaining_sessions": 0,
        "cleanup_receipts_verified": True,
        "recovery_scope_sha256": request["worker"]["recovery_scope_sha256"],
        "wal_snapshot_sha256": hashlib.sha256(b"wal-snapshot").hexdigest(),
        "recovery_receipt_sha256": hashlib.sha256(b"recovery-receipt").hexdigest(),
        "receipt_verifier_sha256": request["worker"]["cleanup_receipt_verifier_sha256"],
    }
elif operation == "probe":
    if fixture["orphan_probe"]:
        child = subprocess.Popen(["sleep", "60"])
        Path(fixture["child_pid_path"]).write_text(str(child.pid))
    elif fixture["slow_probe"]:
        child = subprocess.Popen(["sleep", "60"])
        Path(fixture["child_pid_path"]).write_text(str(child.pid))
        time.sleep(60)
    empty = not request["requirements"]
    satisfied = empty or "/satisfied@" in request["image"]
    inventory = fixture["installed_inventory"] if empty else (
        fixture["satisfied_inventory"] if satisfied else fixture["installed_inventory"]
    )
    result = {
        "image": request["image"],
        "requirements_sha256": request["requirements_sha256"],
        "compatibility": fixture["compatibility"],
        "installed_inventory": inventory,
        "installed_inventory_sha256": fixture[
            "installed_inventory_sha256" if empty or not satisfied else "satisfied_inventory_sha256"
        ],
        "satisfied": satisfied,
        "closure": fixture["empty_closure"] if empty else (
            fixture["build_result"]["closure"] if satisfied else None
        ),
        "attestation": request["attestation_policy"],
    }
elif operation == "build":
    archive = Path(fixture["archive_path"]).read_bytes()
    artifact = args.artifact_dir / "wheelhouse.tar"
    if artifact.exists() and artifact.read_bytes() != archive:
        raise SystemExit(3)
    artifact.write_bytes(archive)
    artifact.chmod(0o400)
    result = fixture["build_result"]
elif operation == "validate":
    archive = Path(request["archive"]["path"])
    if hashlib.sha256(archive.read_bytes()).hexdigest() != request["archive"]["sha256"]:
        raise SystemExit(4)
    evidence = request["validation_evidence"]
    result = {
        "image": request["image"],
        "requirements_sha256": request["requirements_sha256"],
        "runtime_fingerprint_sha256": request["compatibility"]["runtime_fingerprint_sha256"],
        "archive_sha256": request["archive"]["sha256"],
        "closure_sha256": request["closure"]["sha256"],
        "observed": {
            "network": "none",
            "network_isolation_verified": True,
            "archive_sha256": request["archive"]["sha256"],
            "wheel_inventory_sha256": evidence["wheel_inventory_sha256"],
            "install_request_sha256": evidence["install_request_sha256"],
            "install_argv_sha256": evidence["install_argv_sha256"],
            "install_environment_sha256": evidence["install_environment_sha256"],
            "install_exit_code": 7 if __BAD_VALIDATION__ else 0,
            "probe_script_sha256": evidence["probe_script_sha256"],
            "probe_control_sha256": evidence["probe_control_sha256"],
            "probe_argv_sha256": evidence["probe_argv_sha256"],
            "probe_exit_code": 0,
            "probe_stdout_sha256": evidence["expected_probe_stdout_sha256"],
            "observed_inventory_sha256": evidence["expected_inventory_sha256"],
            "observed_closure_sha256": evidence["expected_closure_sha256"],
            "missing_distributions": 0,
            "unexpected_distributions": 0,
        },
    }
else:
    raise SystemExit(5)
lifecycle = {
    "network": "control-plane" if operation == "recover" else (
        "trusted-builder" if operation == "build" else "none"
    ),
    "session_started": operation != "recover",
    "process_cleanup_verified": True,
    "cleanup_verified": __CLEANUP_VERIFIED__,
    "provider_cleanup": None if operation == "recover" else {
        "provider": "sandoq",
        "request_sha256": args.request_sha256,
        "recovery_scope_sha256": request["worker"]["recovery_scope_sha256"],
        "session_sha256": hashlib.sha256((args.request_sha256 + ":session").encode()).hexdigest(),
        "wal_entry_sha256": hashlib.sha256((args.request_sha256 + ":wal").encode()).hexdigest(),
        "receipt_sha256": hashlib.sha256((args.request_sha256 + ":receipt").encode()).hexdigest(),
        "receipt_verifier_sha256": request["worker"]["cleanup_receipt_verifier_sha256"],
        "terminal_state": "deleted",
    },
}
response = {
    "schema_version": 1,
    "protocol_version": request["protocol_version"],
    "operation": operation,
    "request_sha256": args.request_sha256,
    "worker_executable_sha256": request["worker"]["executable_sha256"],
    "worker_runtime_sha256": request["worker"]["runtime_sha256"],
    "worker_environment_sha256": request["worker"]["environment_sha256"],
    "recovery_scope_sha256": request["worker"]["recovery_scope_sha256"],
    "credential_rotation_sha256": request["worker"]["credential_rotation_sha256"],
    "status": "complete",
    "lifecycle": lifecycle,
    "result": result,
}
temporary = args.response.with_suffix(".tmp")
temporary.write_bytes(canonical(response))
temporary.chmod(0o600)
os.replace(temporary, args.response)
args.response.chmod(0o400)
if __EXIT_AFTER_RESPONSE__:
    raise SystemExit(9)
if __HANG_AFTER_RESPONSE__:
    time.sleep(60)
""".replace("__PYTHON__", sys.executable)
        .replace("__FIXTURE_PATH__", repr(str(fixture_path)))
        .replace("__CLEANUP_VERIFIED__", repr(not bad_cleanup))
        .replace("__BAD_VALIDATION__", repr(bad_validation))
        .replace("__EXIT_AFTER_RESPONSE__", repr(exit_after_response))
        .replace("__HANG_AFTER_RESPONSE__", repr(hang_after_response))
    )


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    bad_cleanup: bool = False,
    bad_validation: bool = False,
    slow_probe: bool = False,
    orphan_probe: bool = False,
    rotating_token: bool = False,
    immutable_credential: bool = False,
    exit_after_response: bool = False,
    hang_after_response: bool = False,
):
    project = _private_directory(tmp_path / "project")
    dataset = _private_directory(tmp_path / "dataset")
    plan_root = _private_directory(tmp_path / "plan")
    work_root = _private_directory(tmp_path / "work")
    fixture_root = _private_directory(tmp_path / "worker-fixture")

    marker_environment = {"python_version": "3.12", "sys_platform": "linux"}
    supported_tags = ["py3-none-any"]
    fingerprint = RuntimeFingerprint(
        implementation="cpython",
        python_full_version="3.12.8",
        abi="cpython-312-x86_64-linux-gnu",
        platform="linux-x86_64",
        machine="x86_64",
        libc="glibc-2.36",
        pip_version="24.3.1",
        marker_environment_sha256=_digest(canonical_json(marker_environment)),
        supported_tags_sha256=_digest(canonical_json(supported_tags)),
    )
    wheel_name = "root_pkg-1.0.0-py3-none-any.whl"
    archive = pack_wheelhouse({wheel_name: _wheel("root-pkg", "1.0.0")})
    archive_path = fixture_root / "wheelhouse.tar"
    _write_private(archive_path, archive)
    evidence = inspect_wheelhouse(archive)[0]
    binary_policy = {
        "schema_version": 1,
        "distribution": evidence.distribution,
        "version": evidence.version,
        "filename": evidence.filename,
        "size": evidence.size,
        "sha256": evidence.sha256,
        "source_url_sha256": _digest("binary-source-url"),
        "source_snapshot_sha256": _digest("binary-index-snapshot"),
    }
    binary_policy_sha256 = _digest(canonical_json(binary_policy))
    approved_binaries = [binary_policy_sha256]
    closure = [[evidence.distribution, evidence.version]]
    toolchain = {
        "schema_version": 1,
        "python_version": fingerprint.python_full_version,
        "pip_version": fingerprint.pip_version,
        "resolver": "pip",
        "resolver_version": fingerprint.pip_version,
        "builder_code_sha256": _digest("builder-code"),
        "build_environment_sha256": _digest("builder-environment"),
    }
    toolchain_sha256 = _digest(canonical_json(toolchain))
    source_attestations: list[str] = []
    requirements = ("root-pkg==1.0.0",)
    empty_requirements: tuple[str, ...] = ()
    shared_image = f"registry.invalid/shared@sha256:{'a' * 64}"
    tasks = (
        ExpectedTaskBinding("synthetic-shared", "shared-agent", shared_image, requirements),
        ExpectedTaskBinding("synthetic-shared-copy", "shared-agent", shared_image, requirements),
        ExpectedTaskBinding(
            "synthetic-separate",
            "separate-verifier",
            f"registry.invalid/verifier@sha256:{'b' * 64}",
            requirements,
        ),
        ExpectedTaskBinding(
            "synthetic-satisfied",
            "shared-agent",
            f"registry.invalid/satisfied@sha256:{'c' * 64}",
            requirements,
        ),
        ExpectedTaskBinding(
            "synthetic-empty",
            "shared-agent",
            f"registry.invalid/empty@sha256:{'d' * 64}",
            empty_requirements,
        ),
    )
    identity = CatalogIdentity(
        dataset_revision="1" * 40,
        task_selection_sha256=_digest("selection"),
        expected_task_count=len(tasks),
        binding_plan_sha256=binding_plan_sha256(tasks),
        catalog_consumer_code_sha256=catalog_consumer_code_sha256(),
        image_manifest_sha256=_digest("images"),
        requirements_extractor_sha256=_digest("extractor"),
        inventory_probe_code_sha256=_digest("probe-code"),
        inventory_probe_environment_sha256=_digest("probe-environment"),
        inventory_probe_approval_sha256=_digest("probe-approval"),
        source_policy_sha256=_digest("source-policy"),
        source_policy_approval_sha256=_digest("source-approval"),
        approved_binary_artifacts_sha256=_allowlist_digest("binary-artifacts", approved_binaries),
        approved_source_attestations_sha256=_allowlist_digest("source-attestations", source_attestations),
        approved_toolchains_sha256=_allowlist_digest("toolchains", [toolchain_sha256]),
    )
    installed_inventory = [["ambient-pkg", "9.0.0"]]
    satisfied_inventory = [["ambient-pkg", "9.0.0"], ["root-pkg", "1.0.0"]]
    fixture = {
        "slow_probe": slow_probe,
        "orphan_probe": orphan_probe,
        "child_pid_path": str(fixture_root / "child.pid"),
        "compatibility": {
            "runtime_fingerprint": fingerprint.record(),
            "runtime_fingerprint_sha256": fingerprint.sha256,
            "marker_environment": marker_environment,
            "supported_tags": supported_tags,
        },
        "installed_inventory": installed_inventory,
        "installed_inventory_sha256": closure_sha256(installed_inventory),
        "satisfied_inventory": satisfied_inventory,
        "satisfied_inventory_sha256": closure_sha256(satisfied_inventory),
        "empty_closure": {"distributions": [], "sha256": closure_sha256([])},
        "archive_path": str(archive_path),
        "build_result": {
            "scope": "universal",
            "image": None,
            "archive": {
                "filename": "wheelhouse.tar",
                "sha256": _digest(archive),
                "size": len(archive),
            },
            "closure": {"distributions": closure, "sha256": closure_sha256(closure)},
            "toolchain": {"record": toolchain, "sha256": toolchain_sha256},
            "source_policy": {
                "policy_sha256": identity.source_policy_sha256,
                "approval_sha256": identity.source_policy_approval_sha256,
            },
            "wheels": [
                {
                    "distribution": evidence.distribution,
                    "version": evidence.version,
                    "filename": evidence.filename,
                    "size": evidence.size,
                    "sha256": evidence.sha256,
                    "universal": evidence.universal,
                    "origin": "binary",
                    "binary_artifact_policy": binary_policy,
                    "binary_artifact_policy_sha256": binary_policy_sha256,
                    "source_attestation_sha256": None,
                }
            ],
        },
    }
    fixture_path = fixture_root / "fixture.json"
    _write_private(fixture_path, canonical_json(fixture))
    worker_path = fixture_root / "worker.py"
    _write_private(
        worker_path,
        _worker_script(
            fixture_path,
            bad_cleanup=bad_cleanup,
            bad_validation=bad_validation,
            exit_after_response=exit_after_response,
            hang_after_response=hang_after_response,
        ).encode(),
        mode=0o500,
    )
    worker_sha256 = _digest(worker_path.read_bytes())
    worker_environment_names = [
        "OCI_RUNNER_ENVIRONMENT",
        "OCI_RUNNER_TASK_NETWORK",
        "SANDOQ_OWNER",
        "VF_SANDBOX_PROVIDER",
    ]
    monkeypatch.setenv("OCI_RUNNER_ENVIRONMENT", "oci-runner-firecracker")
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "none")
    monkeypatch.setenv("SANDOQ_OWNER", "synthetic-catalog-owner")
    monkeypatch.setenv("VF_SANDBOX_PROVIDER", "sandoq")
    immutable_credential_path = fixture_root / "immutable-worker-credential"
    if immutable_credential:
        _write_private(immutable_credential_path, b"synthetic-immutable-credential", mode=0o600)
        monkeypatch.setenv("OCI_RUNNER_TOKEN_FILE", str(immutable_credential_path))
        worker_environment_names.append("OCI_RUNNER_TOKEN_FILE")
    token_path = fixture_root / "ecr-token"
    rotator_sha256 = _digest("synthetic-ecr-rotator") if rotating_token else None
    if rotating_token:
        _write_private(token_path, b"synthetic-generation-one", mode=0o600)
        metadata_path = fixture_root / "ecr-token-metadata.json"
        _write_private(
            metadata_path,
            _rotation_metadata(token_path, rotator_sha256, 1),  # type: ignore[arg-type]
            mode=0o600,
        )
        monkeypatch.setenv("OCI_RUNNER_ECR_TOKEN_FILE", str(token_path))
        monkeypatch.setenv("OCI_RUNNER_ECR_TOKEN_METADATA_PATH", str(metadata_path))
        worker_environment_names.append("OCI_RUNNER_ECR_TOKEN_FILE")
        worker_environment_names.append("OCI_RUNNER_ECR_TOKEN_METADATA_PATH")
    worker_environment_names = tuple(sorted(worker_environment_names))
    environment_sha256 = worker_environment_sha256(worker_environment_names)
    worker_policy = WorkerPolicy(
        executable_sha256=worker_sha256,
        runtime_sha256=_digest("worker-runtime"),
        materializer_code_sha256=materializer_controller_code_sha256(),
        cleanup_receipt_verifier_sha256=_digest("cleanup-receipt-verifier"),
        environment_sha256=environment_sha256,
        recovery_scope_sha256=worker_recovery_scope_sha256(environment_sha256),
        ecr_rotator_sha256=rotator_sha256,
        environment_names=worker_environment_names,
        recovery_timeout_seconds=30,
        probe_timeout_seconds=30,
        build_timeout_seconds=30,
        validate_timeout_seconds=30,
        probe_concurrency=4,
        build_concurrency=2,
        validate_concurrency=4,
    )
    plan_payload = materialization_plan_payload(
        identity=identity,
        worker=worker_policy,
        approved_binary_artifacts=approved_binaries,
        approved_source_attestations=source_attestations,
        approved_toolchains=[toolchain_sha256],
        tasks=tasks,
    )
    plan_path = plan_root / "plan.json"
    _write_private(plan_path, plan_payload)
    return {
        "project": project,
        "dataset": dataset,
        "work": work_root,
        "plan": plan_path,
        "plan_sha256": _digest(plan_payload),
        "worker": worker_path,
        "identity": identity,
        "tasks": tasks,
        "fingerprint": fingerprint,
        "child_pid": fixture_root / "child.pid",
        "token": token_path,
        "token_metadata": fixture_root / "ecr-token-metadata.json",
        "immutable_credential": immutable_credential_path,
    }


def test_materializer_runs_all_phases_publishes_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    output = tmp_path / "catalog-output"
    receipt = asyncio.run(
        materialize_catalog(
            plan_path=inputs["plan"],
            plan_sha256=inputs["plan_sha256"],
            worker_path=inputs["worker"],
            work_root=inputs["work"],
            output_root=output,
            project_root=inputs["project"],
            dataset_root=inputs["dataset"],
        )
    )
    assert receipt.tasks == 5
    assert receipt.wheelhouse_tasks == 3
    assert receipt.image_inventory_tasks == 2
    assert receipt.wheelhouses == 1
    assert receipt.shared_agent_tasks == 4
    assert receipt.separate_verifier_tasks == 1
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE((output / "catalog.json").stat().st_mode) == 0o400
    assert stat.S_IMODE((output / "launch.json").stat().st_mode) == 0o400
    public = receipt.to_public_dict()
    assert "sha256" not in json.dumps(public)
    assert "synthetic" not in json.dumps(public)

    launch = json.loads((output / "launch.json").read_bytes())
    catalog = OfflineVerifierCatalog.load(
        output / launch["catalog_file"],
        launch["catalog_sha256"],
        inputs["identity"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    catalog.preflight(inputs["tasks"], expected_task_count=5)
    empty_task = inputs["tasks"][-1]
    empty_plan = catalog.resolve(
        empty_task.task_key,
        empty_task.runtime_role,
        empty_task.image,
        empty_task.requirements,
        inputs["fingerprint"],
    )
    assert empty_plan.guarantee == "image-inventory"
    assert json.loads(empty_plan.probe_control_payload(None))["closure"] == []

    assert len(list((inputs["work"] / "jobs" / "probe").glob("*/*/response.json"))) == 4
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) == 1
    assert len(list((inputs["work"] / "jobs" / "build").glob("*/*/response.json"))) == 1
    assert len(list((inputs["work"] / "jobs" / "validate").glob("*/*/response.json"))) == 2

    resumed_output = tmp_path / "catalog-output-resumed"
    resumed = asyncio.run(
        materialize_catalog(
            plan_path=inputs["plan"],
            plan_sha256=inputs["plan_sha256"],
            worker_path=inputs["worker"],
            work_root=inputs["work"],
            output_root=resumed_output,
            project_root=inputs["project"],
            dataset_root=inputs["dataset"],
        )
    )
    assert resumed == receipt
    assert (resumed_output / "catalog.json").read_bytes() == (output / "catalog.json").read_bytes()
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) == 2


def test_materializer_rejects_unverified_worker_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, bad_cleanup=True)
    output = tmp_path / "catalog-output"
    with pytest.raises(OfflineCatalogError, match="worker_recovery_failed"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=output,
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    assert not output.exists()


def test_materializer_rejects_echoed_policy_without_successful_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, bad_validation=True)
    with pytest.raises(OfflineCatalogError, match="validation_result_invalid"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    assert not list((inputs["work"] / "local-processes").glob("*.json"))
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) >= 2


def test_cancellation_kills_worker_group_and_runs_scoped_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, slow_probe=True)

    async def cancel_during_probe() -> None:
        materialization = asyncio.create_task(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        for _ in range(200):
            if inputs["child_pid"].exists():
                break
            await asyncio.sleep(0.01)
        assert inputs["child_pid"].exists()
        materialization.cancel()
        with pytest.raises(asyncio.CancelledError):
            await materialization

    asyncio.run(cancel_during_probe())
    child_pid = int(inputs["child_pid"].read_text())
    assert _process_start_ticks(child_pid) is None
    assert not list((inputs["work"] / "local-processes").glob("*.json"))
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) >= 2


def test_cancellation_during_spawn_captures_then_cleans_worker_before_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    real_spawn = asyncio.create_subprocess_exec
    spawn_started = asyncio.Event()
    spawn_release = asyncio.Event()
    spawn_calls = 0

    async def delayed_first_spawn(*args, **kwargs):
        nonlocal spawn_calls
        spawn_calls += 1
        if spawn_calls == 1:
            spawn_started.set()
            await spawn_release.wait()
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_first_spawn)

    async def cancel_spawn() -> None:
        materialization = asyncio.create_task(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        await spawn_started.wait()
        materialization.cancel()
        await asyncio.sleep(0)
        spawn_release.set()
        with pytest.raises(asyncio.CancelledError):
            await materialization
        assert materialization.cancelled()

    asyncio.run(cancel_spawn())
    assert not list((inputs["work"] / "local-processes").glob("*.json"))
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) >= 1


def test_repeated_cancellation_during_process_cleanup_cannot_detach_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, slow_probe=True)
    real_terminate_group = materializer_module._terminate_process_group
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def delayed_terminate_group(process_group: int) -> None:
        cleanup_started.set()
        await cleanup_release.wait()
        await real_terminate_group(process_group)

    monkeypatch.setattr(materializer_module, "_terminate_process_group", delayed_terminate_group)

    async def cancel_cleanup_twice() -> None:
        materialization = asyncio.create_task(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        for _ in range(200):
            if inputs["child_pid"].exists():
                break
            await asyncio.sleep(0.01)
        assert inputs["child_pid"].exists()
        materialization.cancel()
        await cleanup_started.wait()
        materialization.cancel()
        await asyncio.sleep(0)
        assert not materialization.done()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await materialization
        assert materialization.cancelled()

    asyncio.run(cancel_cleanup_twice())
    child_pid = int(inputs["child_pid"].read_text())
    assert _process_start_ticks(child_pid) is None
    assert not list((inputs["work"] / "local-processes").glob("*.json"))
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) >= 2


def test_worker_timeout_kills_group_then_runs_local_and_provider_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, slow_probe=True)
    raw_plan = json.loads(inputs["plan"].read_bytes())
    raw_plan["worker"]["timeouts_seconds"]["probe"] = 1
    payload = canonical_json(raw_plan)
    inputs["plan"].chmod(0o600)
    inputs["plan"].write_bytes(payload)
    inputs["plan"].chmod(0o400)
    with pytest.raises(OfflineCatalogError, match="worker_probe_timeout"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=_digest(payload),
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    child_pid = int(inputs["child_pid"].read_text())
    assert _process_start_ticks(child_pid) is None
    assert not list((inputs["work"] / "local-processes").glob("*.json"))
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) >= 2


def test_exited_worker_leader_with_live_descendant_is_killed_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, orphan_probe=True)
    raw_plan = json.loads(inputs["plan"].read_bytes())
    raw_plan["worker"]["concurrency"]["probe"] = 1
    payload = canonical_json(raw_plan)
    inputs["plan"].chmod(0o600)
    inputs["plan"].write_bytes(payload)
    inputs["plan"].chmod(0o400)
    with pytest.raises(OfflineCatalogError, match="worker_process_group_leaked"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=_digest(payload),
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    child_pid = int(inputs["child_pid"].read_text())
    assert _process_start_ticks(child_pid) is None
    assert not list((inputs["work"] / "local-processes").glob("*.json"))
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) >= 2


def test_local_group_cleanup_failure_blocks_post_failure_provider_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, slow_probe=True)
    real_terminate_stale = materializer_module._terminate_stale_process_group

    async def fail_initial_group_cleanup(_process_group: int) -> None:
        raise OfflineCatalogError("synthetic_group_cleanup_failure")

    async def kill_then_fail_stale_cleanup(process_group: int, pid: int) -> None:
        await real_terminate_stale(process_group, pid)
        raise OfflineCatalogError("synthetic_stale_group_cleanup_failure")

    monkeypatch.setattr(materializer_module, "_terminate_process_group", fail_initial_group_cleanup)
    monkeypatch.setattr(materializer_module, "_terminate_stale_process_group", kill_then_fail_stale_cleanup)

    async def cancel_probe() -> None:
        materialization = asyncio.create_task(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        for _ in range(200):
            if inputs["child_pid"].exists():
                break
            await asyncio.sleep(0.01)
        assert inputs["child_pid"].exists()
        materialization.cancel()
        with pytest.raises(OfflineCatalogError, match="worker_local_recovery_failed"):
            await materialization

    asyncio.run(cancel_probe())
    records = list((inputs["work"] / "local-processes").glob("*.json"))
    assert records
    process_records = [json.loads(record.read_bytes()) for record in records]
    assert any(materializer_module._process_group_exists(record["process_group"]) for record in process_records)
    # One initial provider recovery ran; the failed local cleanup prevents a
    # second provider recovery from claiming the scope is clean.
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) == 1

    async def clean_synthetic_groups() -> None:
        for record in process_records:
            if materializer_module._process_group_exists(record["process_group"]):
                await real_terminate_stale(record["process_group"], record["pid"])

    asyncio.run(clean_synthetic_groups())


def test_startup_kills_a_wal_bound_stale_local_worker_before_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    process = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        start_ticks = _process_start_ticks(process.pid)
        assert start_ticks is not None
        process_root = inputs["work"] / "local-processes"
        process_root.mkdir(mode=0o700)
        _write_private(
            process_root / f"{'e' * 64}.json",
            canonical_json(
                {
                    "schema_version": 1,
                    "request_sha256": "e" * 64,
                    "recovery_scope_sha256": json.loads(inputs["plan"].read_bytes())["worker"]["recovery_scope_sha256"],
                    "pid": process.pid,
                    "process_group": process.pid,
                    "start_ticks": start_ticks,
                }
            ),
        )
        receipt = asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        assert receipt.tasks == 5
        assert _process_start_ticks(process.pid) is None
        assert not list(process_root.glob("*.json"))
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def test_startup_refuses_to_signal_live_group_after_recorded_leader_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    runner = WorkerRunner(inputs["worker"], plan.worker, inputs["work"])
    fake_pid = 2_000_000_003
    record = inputs["work"] / "local-processes" / f"{'b' * 64}.json"
    _write_private(
        record,
        canonical_json(
            {
                "schema_version": 1,
                "request_sha256": "b" * 64,
                "recovery_scope_sha256": plan.worker.recovery_scope_sha256,
                "pid": fake_pid,
                "process_group": fake_pid,
                "start_ticks": 12347,
            }
        ),
    )
    real_process_start_ticks = materializer_module._process_start_ticks
    real_process_group_exists = materializer_module._process_group_exists
    monkeypatch.setattr(
        materializer_module,
        "_process_start_ticks",
        lambda pid: None if pid == fake_pid else real_process_start_ticks(pid),
    )
    monkeypatch.setattr(
        materializer_module,
        "_process_group_exists",
        lambda process_group: True if process_group == fake_pid else real_process_group_exists(process_group),
    )
    signalled = False

    async def must_not_signal(_process_group: int, _pid: int) -> None:
        nonlocal signalled
        signalled = True

    monkeypatch.setattr(materializer_module, "_terminate_stale_process_group", must_not_signal)
    with pytest.raises(OfflineCatalogError, match="worker_process_identity_ambiguous"):
        asyncio.run(runner.recover_stale_local_processes())
    assert not signalled
    assert record.exists()


def test_repeated_cancellation_during_startup_wal_recovery_drains_and_recovers_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    fake_pid = 2_000_000_001
    fake_start_ticks = 12345
    process_root = inputs["work"] / "local-processes"
    process_root.mkdir(mode=0o700)
    record = process_root / f"{'d' * 64}.json"
    _write_private(
        record,
        canonical_json(
            {
                "schema_version": 1,
                "request_sha256": "d" * 64,
                "recovery_scope_sha256": json.loads(inputs["plan"].read_bytes())["worker"][
                    "recovery_scope_sha256"
                ],
                "pid": fake_pid,
                "process_group": fake_pid,
                "start_ticks": fake_start_ticks,
            }
        ),
    )
    real_process_start_ticks = materializer_module._process_start_ticks
    real_getpgid = os.getpgid
    monkeypatch.setattr(
        materializer_module,
        "_process_start_ticks",
        lambda pid: fake_start_ticks if pid == fake_pid else real_process_start_ticks(pid),
    )
    monkeypatch.setattr(os, "getpgid", lambda pid: fake_pid if pid == fake_pid else real_getpgid(pid))
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def fake_terminate_stale(process_group: int, pid: int) -> None:
        assert process_group == fake_pid
        assert pid == fake_pid
        cleanup_started.set()
        await cleanup_release.wait()
        cleanup_finished.set()

    monkeypatch.setattr(materializer_module, "_terminate_stale_process_group", fake_terminate_stale)

    async def cancel_startup_twice() -> None:
        materialization = asyncio.create_task(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        await cleanup_started.wait()
        materialization.cancel()
        await asyncio.sleep(0)
        materialization.cancel()
        await asyncio.sleep(0)
        assert not materialization.done()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await materialization
        assert materialization.cancelled()

    asyncio.run(cancel_startup_twice())
    assert cleanup_finished.is_set()
    assert not record.exists()
    assert len(list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))) == 1


def test_startup_wal_unlink_failure_is_chained_beneath_pending_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    fake_pid = 2_000_000_002
    fake_start_ticks = 12346
    process_root = inputs["work"] / "local-processes"
    process_root.mkdir(mode=0o700)
    record = process_root / f"{'c' * 64}.json"
    _write_private(
        record,
        canonical_json(
            {
                "schema_version": 1,
                "request_sha256": "c" * 64,
                "recovery_scope_sha256": json.loads(inputs["plan"].read_bytes())["worker"][
                    "recovery_scope_sha256"
                ],
                "pid": fake_pid,
                "process_group": fake_pid,
                "start_ticks": fake_start_ticks,
            }
        ),
    )
    real_process_start_ticks = materializer_module._process_start_ticks
    real_getpgid = os.getpgid
    monkeypatch.setattr(
        materializer_module,
        "_process_start_ticks",
        lambda pid: fake_start_ticks if pid == fake_pid else real_process_start_ticks(pid),
    )
    monkeypatch.setattr(os, "getpgid", lambda pid: fake_pid if pid == fake_pid else real_getpgid(pid))
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def fake_terminate_stale(process_group: int, pid: int) -> None:
        assert process_group == fake_pid
        assert pid == fake_pid
        cleanup_started.set()
        await cleanup_release.wait()

    monkeypatch.setattr(materializer_module, "_terminate_stale_process_group", fake_terminate_stale)
    real_remove_process_record = WorkerRunner._remove_process_record  # noqa: SLF001

    def fail_target_record_removal(runner: WorkerRunner, path: Path) -> None:
        if path == record:
            raise RuntimeError("synthetic WAL unlink failure")
        real_remove_process_record(runner, path)

    monkeypatch.setattr(WorkerRunner, "_remove_process_record", fail_target_record_removal)

    async def cancel_before_unlink() -> None:
        materialization = asyncio.create_task(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
        await cleanup_started.wait()
        materialization.cancel()
        await asyncio.sleep(0)
        cleanup_release.set()
        with pytest.raises(OfflineCatalogError, match="worker_local_recovery_failed") as raised:
            await materialization
        assert isinstance(raised.value.__cause__, RuntimeError)

    asyncio.run(cancel_before_unlink())
    assert record.exists()
    assert not list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))


def test_bounded_map_repeated_cancellation_drains_all_child_cleanup() -> None:
    async def cancel_batch_twice() -> None:
        all_started = asyncio.Event()
        all_cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        started = 0
        cleanup_started = 0
        cleanup_finished = 0

        async def operation(_item: object) -> object:
            nonlocal started, cleanup_started, cleanup_finished
            started += 1
            if started == 2:
                all_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started += 1
                if cleanup_started == 2:
                    all_cleanup_started.set()
                await cleanup_release.wait()
                cleanup_finished += 1

        batch = asyncio.create_task(_bounded_map((1, 2), 2, operation))
        await all_started.wait()
        batch.cancel()
        await all_cleanup_started.wait()
        batch.cancel()
        await asyncio.sleep(0)
        assert not batch.done()
        assert cleanup_finished == 0
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await batch
        assert batch.cancelled()
        assert cleanup_finished == 2

    asyncio.run(cancel_batch_twice())


def test_bounded_map_child_failure_drains_sibling_cleanup_before_returning() -> None:
    async def fail_one_child() -> None:
        sibling_started = asyncio.Event()
        sibling_cleanup_started = asyncio.Event()
        sibling_cleanup_release = asyncio.Event()
        sibling_cleanup_finished = asyncio.Event()

        async def operation(item: object) -> object:
            if item == "failure":
                await sibling_started.wait()
                raise RuntimeError("synthetic worker failure")
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cleanup_started.set()
                await sibling_cleanup_release.wait()
                sibling_cleanup_finished.set()

        batch = asyncio.create_task(_bounded_map(("failure", "sibling"), 2, operation))
        await sibling_cleanup_started.wait()
        assert not batch.done()
        sibling_cleanup_release.set()
        with pytest.raises(RuntimeError, match="synthetic worker failure"):
            await batch
        assert sibling_cleanup_finished.is_set()

    asyncio.run(fail_one_child())


def test_drain_task_preserves_cancellation_when_cleanup_later_fails() -> None:
    async def cancel_before_failure() -> None:
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()

        async def delayed_failure() -> None:
            cleanup_started.set()
            await cleanup_release.wait()
            raise RuntimeError("synthetic cleanup failure")

        async def drain() -> None:
            cleanup = asyncio.create_task(delayed_failure())
            await _drain_task(cleanup)

        outer = asyncio.create_task(drain())
        await cleanup_started.wait()
        outer.cancel()
        await asyncio.sleep(0)
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await outer
        assert outer.cancelled()
        assert isinstance(raised.value.__cause__, RuntimeError)

    asyncio.run(cancel_before_failure())


def test_bounded_map_retains_child_cleanup_failure_on_cancellation() -> None:
    async def cancel_with_cleanup_failure() -> None:
        operation_started = asyncio.Event()
        cleanup_release = asyncio.Event()

        async def operation(_item: object) -> object:
            operation_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleanup_release.wait()
                raise RuntimeError("synthetic child cleanup failure")

        batch = asyncio.create_task(_bounded_map((1,), 1, operation))
        await operation_started.wait()
        batch.cancel()
        await asyncio.sleep(0)
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await batch
        assert batch.cancelled()
        assert isinstance(raised.value.__cause__, RuntimeError)

    asyncio.run(cancel_with_cleanup_failure())


def test_materialization_lock_is_kernel_held_and_recoverable(tmp_path: Path) -> None:
    lock_path = tmp_path / "materialize.lock"
    with _ExclusiveFileLock(lock_path, "locked"):
        with pytest.raises(OfflineCatalogError, match="locked"):
            with _ExclusiveFileLock(lock_path, "locked"):
                pass
    with _ExclusiveFileLock(lock_path, "locked"):
        pass


def test_materializer_rejects_nonprivate_work_and_output_parent_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    inputs["work"].chmod(0o755)
    with pytest.raises(OfflineCatalogError, match="catalog_root_invalid"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    inputs["work"].chmod(0o700)
    tmp_path.chmod(0o755)
    with pytest.raises(OfflineCatalogError, match="catalog_output_invalid"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )


def test_materializer_rejects_hardlinked_plan_and_output_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    os.link(inputs["plan"], inputs["plan"].with_suffix(".hardlink"))
    with pytest.raises(OfflineCatalogError, match="materialization_plan_invalid"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    inputs["plan"].with_suffix(".hardlink").unlink()
    with pytest.raises(OfflineCatalogError, match="catalog_output_overlap"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=inputs["project"] / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )


def test_immediate_exit_is_accepted_only_after_atomic_response_and_group_extinction(
    tmp_path: Path,
) -> None:
    response = tmp_path / "response.json"
    response.write_text("{}")
    runner = object.__new__(WorkerRunner)
    process = SimpleNamespace(pid=2_000_000_000, returncode=0)
    assert (
        asyncio.run(runner._record_process("f" * 64, process, response))  # noqa: SLF001
        is None
    )


def test_worker_policy_rejects_direct_secret_environment_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    raw_plan = json.loads(inputs["plan"].read_bytes())
    raw_worker = raw_plan["worker"]
    bad_worker = WorkerPolicy(
        executable_sha256=raw_worker["executable_sha256"],
        runtime_sha256=raw_worker["runtime_sha256"],
        materializer_code_sha256=raw_worker["materializer_code_sha256"],
        cleanup_receipt_verifier_sha256=raw_worker["cleanup_receipt_verifier_sha256"],
        environment_sha256=raw_worker["environment_sha256"],
        recovery_scope_sha256=raw_worker["recovery_scope_sha256"],
        ecr_rotator_sha256=raw_worker["ecr_rotator_sha256"],
        environment_names=("AWS_SECRET_ACCESS_KEY",),
        recovery_timeout_seconds=raw_worker["timeouts_seconds"]["recover"],
        probe_timeout_seconds=raw_worker["timeouts_seconds"]["probe"],
        build_timeout_seconds=raw_worker["timeouts_seconds"]["build"],
        validate_timeout_seconds=raw_worker["timeouts_seconds"]["validate"],
        probe_concurrency=raw_worker["concurrency"]["probe"],
        build_concurrency=raw_worker["concurrency"]["build"],
        validate_concurrency=raw_worker["concurrency"]["validate"],
    )
    with pytest.raises(OfflineCatalogError, match="worker_policy_invalid"):
        materialization_plan_payload(
            identity=inputs["identity"],
            worker=bad_worker,
            approved_binary_artifacts=raw_plan["policy"]["approved_binary_artifacts"],
            approved_source_attestations=raw_plan["policy"]["approved_source_attestations"],
            approved_toolchains=raw_plan["policy"]["approved_toolchains"],
            tasks=inputs["tasks"],
        )


def test_environment_drift_is_rejected_before_cached_work_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "bridge")
    with pytest.raises(OfflineCatalogError, match="worker_environment_invalid"):
        asyncio.run(
            materialize_catalog(
                plan_path=inputs["plan"],
                plan_sha256=inputs["plan_sha256"],
                worker_path=inputs["worker"],
                work_root=inputs["work"],
                output_root=tmp_path / "catalog-output",
                project_root=inputs["project"],
                dataset_root=inputs["dataset"],
            )
        )
    assert not (inputs["work"] / "jobs").exists()


def test_cached_response_revalidates_staged_worker_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    runner = WorkerRunner(inputs["worker"], plan.worker, inputs["work"])
    request = _recovery_request(plan.worker, "0" * 32)
    asyncio.run(runner.invoke(request))
    staged_worker = runner.executable.path
    staged_worker.chmod(0o700)
    staged_worker.write_bytes(staged_worker.read_bytes() + b"changed")
    staged_worker.chmod(0o500)
    with pytest.raises(OfflineCatalogError, match="worker_executable_changed"):
        asyncio.run(runner.invoke(request))


def test_response_written_before_nonzero_exit_never_becomes_cached_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, exit_after_response=True)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    runner = WorkerRunner(inputs["worker"], plan.worker, inputs["work"])
    request = _recovery_request(plan.worker, "1" * 32)
    with pytest.raises(OfflineCatalogError, match="worker_recover_failed"):
        asyncio.run(runner.invoke(request))
    assert list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))
    assert not list((inputs["work"] / "jobs" / "recover").glob("*/*/controller-completion.json"))
    with pytest.raises(OfflineCatalogError, match="worker_response_incomplete"):
        asyncio.run(runner.invoke(request))


def test_response_written_before_timeout_never_becomes_cached_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, hang_after_response=True)
    raw_plan = json.loads(inputs["plan"].read_bytes())
    raw_plan["worker"]["timeouts_seconds"]["recover"] = 1
    payload = canonical_json(raw_plan)
    inputs["plan"].chmod(0o600)
    inputs["plan"].write_bytes(payload)
    inputs["plan"].chmod(0o400)
    plan = MaterializationPlan.load(
        inputs["plan"],
        _digest(payload),
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    runner = WorkerRunner(inputs["worker"], plan.worker, inputs["work"])
    request = _recovery_request(plan.worker, "2" * 32)
    with pytest.raises(OfflineCatalogError, match="worker_recover_timeout"):
        asyncio.run(runner.invoke(request))
    assert list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))
    assert not list((inputs["work"] / "jobs" / "recover").glob("*/*/controller-completion.json"))
    with pytest.raises(OfflineCatalogError, match="worker_response_incomplete"):
        asyncio.run(runner.invoke(request))


def test_response_written_before_cancellation_never_becomes_cached_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, hang_after_response=True)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    runner = WorkerRunner(inputs["worker"], plan.worker, inputs["work"])
    request = _recovery_request(plan.worker, "3" * 32)

    async def cancel_after_response() -> None:
        invocation = asyncio.create_task(runner.invoke(request))
        for _ in range(200):
            if list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json")):
                break
            await asyncio.sleep(0.01)
        assert list((inputs["work"] / "jobs" / "recover").glob("*/*/response.json"))
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation

    asyncio.run(cancel_after_response())
    assert not list((inputs["work"] / "jobs" / "recover").glob("*/*/controller-completion.json"))
    with pytest.raises(OfflineCatalogError, match="worker_response_incomplete"):
        asyncio.run(runner.invoke(request))


def test_atomic_ecr_token_rotation_updates_private_audit_without_config_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, rotating_token=True)
    replacement = inputs["token"].with_suffix(".next")
    _write_private(replacement, b"synthetic-generation-two", mode=0o600)
    os.replace(replacement, inputs["token"])
    metadata_replacement = inputs["token_metadata"].with_suffix(".next")
    rotator_sha256 = json.loads(inputs["plan"].read_bytes())["worker"]["ecr_rotator_sha256"]
    _write_private(
        metadata_replacement,
        _rotation_metadata(inputs["token"], rotator_sha256, 2),
        mode=0o600,
    )
    os.replace(metadata_replacement, inputs["token_metadata"])
    receipt = asyncio.run(
        materialize_catalog(
            plan_path=inputs["plan"],
            plan_sha256=inputs["plan_sha256"],
            worker_path=inputs["worker"],
            work_root=inputs["work"],
            output_root=tmp_path / "catalog-output",
            project_root=inputs["project"],
            dataset_root=inputs["dataset"],
        )
    )
    assert receipt.tasks == 5
    requests = list((inputs["work"] / "jobs" / "probe").glob("*/*/request.json"))
    assert requests
    assert all(len(json.loads(path.read_bytes())["worker"]["credential_rotation_sha256"]) == 64 for path in requests)


def test_credential_file_must_be_owned_private_and_single_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = tmp_path / "token"
    _write_private(token, b"synthetic-token", mode=0o600)
    os.link(token, tmp_path / "token-hardlink")
    monkeypatch.setenv("OCI_RUNNER_TOKEN_FILE", str(token))
    monkeypatch.setenv("OCI_RUNNER_ENVIRONMENT", "oci-runner-firecracker")
    monkeypatch.setenv("OCI_RUNNER_TASK_NETWORK", "none")
    monkeypatch.setenv("SANDOQ_OWNER", "synthetic-catalog-owner")
    monkeypatch.setenv("VF_SANDBOX_PROVIDER", "sandoq")
    with pytest.raises(OfflineCatalogError, match="worker_credential_file_invalid"):
        worker_environment_sha256(
            (
                "OCI_RUNNER_ENVIRONMENT",
                "OCI_RUNNER_TASK_NETWORK",
                "OCI_RUNNER_TOKEN_FILE",
                "SANDOQ_OWNER",
                "VF_SANDBOX_PROVIDER",
            )
        )


def test_immutable_credential_swap_and_restore_cannot_change_staged_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, immutable_credential=True)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    credential = inputs["immutable_credential"]
    credential_parent = credential.parent
    original_parent = credential_parent.with_name(f"{credential_parent.name}-original")
    replacement_parent = _private_directory(credential_parent.with_name(f"{credential_parent.name}-replacement"))
    swapped_parent = credential_parent.with_name(f"{credential_parent.name}-swapped")
    _write_private(
        replacement_parent / credential.name,
        b"synthetic-swapped-credential",
        mode=0o600,
    )
    real_record = materializer_module._credential_file_record
    record_calls = 0
    restored = False

    def swap_before_staging_record(value: str):
        nonlocal record_calls, restored
        if Path(value) == credential:
            record_calls += 1
            if record_calls == 2:
                credential_parent.rename(original_parent)
                replacement_parent.rename(credential_parent)
                result = real_record(value)
                credential_parent.rename(swapped_parent)
                original_parent.rename(credential_parent)
                restored = True
                return result
        return real_record(value)

    monkeypatch.setattr(materializer_module, "_credential_file_record", swap_before_staging_record)
    with pytest.raises(OfflineCatalogError, match="worker_credential_file_changed"):
        WorkerRunner(inputs["worker"], plan.worker, inputs["work"])
    assert restored
    assert credential.read_bytes() == b"synthetic-immutable-credential"


def test_rotating_credential_requires_fresh_heartbeat_and_expiry_margin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, rotating_token=True)
    metadata = json.loads(inputs["token_metadata"].read_bytes())
    now = int(time.time())
    metadata["issued_at_unix"] = now - 2000
    metadata["heartbeat_at_unix"] = now - 1000
    metadata["expires_at_unix"] = now + 3600
    inputs["token_metadata"].write_bytes(canonical_json(metadata))
    rotator_sha256 = json.loads(inputs["plan"].read_bytes())["worker"]["ecr_rotator_sha256"]
    with pytest.raises(OfflineCatalogError, match="worker_credential_rotation_invalid"):
        _rotation_audit_record(
            inputs["token"],
            inputs["token_metadata"],
            rotator_sha256,
        )


def test_recovery_result_rejects_boolean_remaining_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    response = WorkerResponse(
        result={
            "durable_provider_wal": True,
            "recovery_attempted": True,
            "remaining_sessions": False,
            "cleanup_receipts_verified": True,
            "recovery_scope_sha256": plan.worker.recovery_scope_sha256,
            "wal_snapshot_sha256": _digest("wal"),
            "recovery_receipt_sha256": _digest("receipt"),
            "receipt_verifier_sha256": plan.worker.cleanup_receipt_verifier_sha256,
        },
        artifact_directory=tmp_path,
    )
    with pytest.raises(OfflineCatalogError, match="worker_recovery_unverified"):
        _parse_recovery_result(response, plan.worker)


def test_empty_requirements_probe_requires_exact_empty_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    plan = MaterializationPlan.load(
        inputs["plan"],
        inputs["plan_sha256"],
        project_root=inputs["project"],
        dataset_root=inputs["dataset"],
    )
    task = next(task for task in plan.tasks if not task.requirements)
    assert not task.requirements
    marker_environment = {"python_version": "3.12", "sys_platform": "linux"}
    supported_tags = ["py3-none-any"]
    inventory = [["ambient-pkg", "9.0.0"]]
    response = WorkerResponse(
        result={
            "image": task.image,
            "requirements_sha256": task.requirements_sha256,
            "compatibility": {
                "runtime_fingerprint": inputs["fingerprint"].record(),
                "runtime_fingerprint_sha256": inputs["fingerprint"].sha256,
                "marker_environment": marker_environment,
                "supported_tags": supported_tags,
            },
            "installed_inventory": inventory,
            "installed_inventory_sha256": closure_sha256(inventory),
            "satisfied": True,
            "closure": {
                "distributions": inventory,
                "sha256": closure_sha256(inventory),
            },
            "attestation": {
                "code_sha256": plan.identity.inventory_probe_code_sha256,
                "environment_sha256": plan.identity.inventory_probe_environment_sha256,
                "approval_sha256": plan.identity.inventory_probe_approval_sha256,
            },
        },
        artifact_directory=tmp_path,
    )
    with pytest.raises(OfflineCatalogError, match="probe_result_invalid"):
        _parse_probe_result(response, task, plan)


def test_publish_rename_never_replaces_an_existing_empty_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir(mode=0o700)
    destination.mkdir(mode=0o700)
    with pytest.raises(OfflineCatalogError, match="catalog_output_changed"):
        _rename_noreplace(source, destination)
    assert source.is_dir()
    assert destination.is_dir()


@pytest.mark.parametrize(
    "mutation",
    [
        "launch-content",
        "launch-hardlink",
        "launch-symlink",
        "launch-race",
        "root-mode-race",
        "extra-race",
        "extra-file",
    ],
)
def test_staging_tree_seal_rejects_launch_mutation_and_unexpected_entries(
    tmp_path: Path,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = _private_directory(tmp_path / "staging")
    launch = staging / "launch.json"
    payload = canonical_json({"schema_version": 1})
    _write_private(launch, payload)
    expected = {"launch.json": (_digest(payload), len(payload))}
    if mutation == "launch-content":
        launch.chmod(0o600)
        launch.write_bytes(payload + b"changed")
        launch.chmod(0o400)
    elif mutation == "launch-hardlink":
        os.link(launch, staging / "launch-copy.json")
    elif mutation == "launch-symlink":
        external = tmp_path / "external-launch.json"
        _write_private(external, payload)
        launch.unlink()
        launch.symlink_to(external)
    elif mutation in {"launch-race", "root-mode-race", "extra-race"}:
        if mutation == "launch-race":
            replacement = tmp_path / "replacement-launch.json"
            _write_private(replacement, payload)
            displaced = tmp_path / "launch-original.json"
        real_read = materializer_module.os.read
        mutated = False

        def swap_after_open(descriptor: int, size: int) -> bytes:
            nonlocal mutated
            observed = real_read(descriptor, size)
            if observed and not mutated:
                if mutation == "launch-race":
                    launch.rename(displaced)
                    replacement.rename(launch)
                elif mutation == "root-mode-race":
                    staging.chmod(0o755)
                else:
                    _write_private(staging / "late-extra.json", b"{}")
                mutated = True
            return observed

        monkeypatch.setattr(materializer_module.os, "read", swap_after_open)
    else:
        _write_private(staging / "unexpected.json", b"{}")
    descriptor = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        with pytest.raises(OfflineCatalogError, match="catalog_staging_invalid"):
            _seal_and_fsync_directory_tree(descriptor, expected)
    finally:
        os.close(descriptor)


def test_publish_rejects_output_parent_path_swap(tmp_path: Path) -> None:
    parent = _private_directory(tmp_path / "parent")
    staging = _private_directory(parent / "staging")
    parent_descriptor, parent_status, _ = _open_absolute_nofollow(parent, "test_invalid")
    parent_identity = _directory_identity(parent_status, "test_invalid")
    staging_identity = _directory_identity(staging.stat(), "test_invalid")
    displaced = tmp_path / "parent-displaced"
    parent.rename(displaced)
    _private_directory(parent)
    try:
        with pytest.raises(OfflineCatalogError, match="catalog_output_changed"):
            _rename_noreplace_at(
                parent_descriptor,
                parent,
                parent_identity,
                "staging",
                "catalog-output",
                staging_identity,
            )
    finally:
        os.close(parent_descriptor)
    assert (displaced / "staging").is_dir()
    assert not (displaced / "catalog-output").exists()


def test_publish_rejects_staging_name_inode_swap(tmp_path: Path) -> None:
    parent = _private_directory(tmp_path / "parent")
    staging = _private_directory(parent / "staging")
    replacement = _private_directory(parent / "replacement")
    parent_descriptor, parent_status, _ = _open_absolute_nofollow(parent, "test_invalid")
    parent_identity = _directory_identity(parent_status, "test_invalid")
    staging_identity = _directory_identity(staging.stat(), "test_invalid")
    staging.rename(parent / "original-staging")
    replacement.rename(staging)
    try:
        with pytest.raises(OfflineCatalogError, match="catalog_staging_invalid"):
            _rename_noreplace_at(
                parent_descriptor,
                parent,
                parent_identity,
                "staging",
                "catalog-output",
                staging_identity,
            )
    finally:
        os.close(parent_descriptor)
    assert (parent / "original-staging").is_dir()
    assert staging.is_dir()


@pytest.mark.parametrize("swap", ["destination", "parent"])
def test_post_publish_scan_rejects_destination_and_parent_swaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap: str,
) -> None:
    parent = _private_directory(tmp_path / "parent")
    destination = _private_directory(parent / "catalog-output")
    launch = destination / "launch.json"
    payload = canonical_json({"schema_version": 1})
    _write_private(launch, payload)
    expected = {"launch.json": (_digest(payload), len(payload))}
    parent_descriptor, parent_status, _ = _open_absolute_nofollow(parent, "test_invalid")
    parent_identity = _directory_identity(parent_status, "test_invalid")
    destination_descriptor = os.open(
        destination,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    destination_identity = _directory_identity(os.fstat(destination_descriptor), "test_invalid")
    replacement = _private_directory(tmp_path / "replacement") if swap == "destination" else None
    real_read = materializer_module.os.read
    swapped = False

    def swap_during_final_scan(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        observed = real_read(descriptor, size)
        if observed and not swapped:
            if swap == "destination":
                destination.rename(parent / "catalog-original")
                assert replacement is not None
                replacement.rename(destination)
            else:
                parent.rename(tmp_path / "parent-original")
                _private_directory(parent)
            swapped = True
        return observed

    monkeypatch.setattr(materializer_module.os, "read", swap_during_final_scan)
    try:
        _seal_and_fsync_directory_tree(destination_descriptor, expected)
        with pytest.raises(OfflineCatalogError, match="catalog_publish_failed"):
            _revalidate_named_directory(
                parent_descriptor,
                parent,
                parent_identity,
                "catalog-output",
                destination_identity,
                "catalog_publish_failed",
            )
    finally:
        os.close(destination_descriptor)
        os.close(parent_descriptor)


def test_cli_surfaces_cleanup_failure_instead_of_collapsing_to_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = SimpleNamespace(
        plan=None,
        plan_sha256=None,
        worker=None,
        work_root=None,
        output_root=None,
        project_root=None,
        dataset_root=None,
    )
    monkeypatch.setattr(materializer_module, "_parse_args", lambda: arguments)

    async def fail_cleanup(**_arguments) -> None:
        try:
            raise asyncio.CancelledError
        except asyncio.CancelledError as cancellation:
            raise OfflineCatalogError("worker_local_recovery_failed") from cancellation

    monkeypatch.setattr(materializer_module, "_materialize_with_signal_teardown", fail_cleanup)
    assert materializer_module.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed",
        "error_code": "worker_local_recovery_failed",
    }
