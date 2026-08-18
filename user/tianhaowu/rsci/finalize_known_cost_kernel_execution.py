#!/usr/bin/env python3
"""Build and statically replay the known-cost kernel execution receipt."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import source_provenance

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_kernel_execution_receipt"
WITNESS_ARTIFACT_TYPE = "rsci_known_cost_kernel_pre_execution_witness"
AMENDMENT_ARTIFACT_TYPE = "rsci_known_cost_kernel_scheduler_amendment"
ENVELOPE_ARTIFACT_TYPE = "rsci_known_cost_kernel_scheduler_final_envelope"
RECEIPT_NAME = "kernel_execution_receipt.json"
WITNESS_NAME = "kernel_pre_execution_witness.json"
AMENDMENT_NAME = "kernel_scheduler_amendment.json"
ENVELOPE_NAME = "kernel_scheduler_final_envelope.json"
KERNEL_RESULT_NAME = "kernel.json"
KERNEL_VALIDATION_NAME = "kernel_validation.json"
PRODUCTION_KERNEL_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2")
CONTROL_PLANE_SOURCE_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-control-plane-v1")
PRODUCTION_WITNESS_SHA256 = "d40a3e204749a7f9b44354710011234ecc787625be9a89b9dc0dcfb038a931a5"
PRODUCTION_WITNESS_SIZE_BYTES = 3214
PRODUCTION_AMENDMENT_SHA256 = "e1653e29fc97b48f688f7a67f0a1f90c205141552dd2591d91e5b883752ca81f"
PRODUCTION_AMENDMENT_SIZE_BYTES = 1261
PRODUCTION_ENVELOPE_SHA256 = "0c45c85b28cef5d2b346bbe24ecf931ff03d8d8a090eb2935a71dae920df7919"
PRODUCTION_ENVELOPE_SIZE_BYTES = 1832
GPU_JOB_ID = "10278600"
VALIDATOR_JOB_ID = "10278639"
GPU_JOB_NAME = "rsci-known-cost-kernel-v2"
VALIDATOR_JOB_NAME = "rsci-kc-kernel-v2-validate"
GPU_SUBMIT_QOS = "h100_lowest"
GPU_FINAL_QOS = "h100_dev"
VALIDATOR_QOS = "cpu_lowest"
ACCOUNT = "ram"
IMPLEMENTATION_REPOSITORY_PATH = "user/tianhaowu/rsci/finalize_known_cost_kernel_execution.py"
KERNEL_VALIDATION_FIELDS = {
    "command",
    "eligible_design",
    "finite_step_ordering_passed",
    "median_off_diagonal",
    "output",
    "output_sha256",
}
SACCT_FIELDS = (
    "JobIDRaw",
    "JobName",
    "State",
    "ExitCode",
    "Submit",
    "Start",
    "End",
    "ElapsedRaw",
    "QOS",
    "Account",
    "Comment",
    "Timelimit",
    "TimelimitRaw",
)
WITNESS_TOP_FIELDS = {
    "artifact_type",
    "checks",
    "gpu_job",
    "observed_at",
    "output_paths",
    "probe",
    "schema_version",
    "source",
    "validator_job",
}
WITNESS_CHECK_FIELDS = {
    "gpu_job_had_never_started",
    "gpu_job_pending",
    "kernel_log_absent",
    "kernel_result_absent",
    "kernel_validation_absent",
    "validator_dependency_unfulfilled",
}
RECEIPT_CHECK_FIELDS = {
    "control_plane_source_provenance_is_commit_and_environment_pinned",
    "gpu_job_completed_with_zero_exit_and_positive_elapsed",
    "gpu_log_final_summary_proves_fresh_execution",
    "kernel_result_passes_pinned_static_validator",
    "pre_execution_witness_is_exact_and_immutable",
    "scheduler_amendment_is_exact_and_pre_execution",
    "scheduler_final_envelope_is_exact_and_pre_execution",
    "submitted_gpu_and_validator_scripts_match_witness",
    "validator_job_completed_with_zero_exit",
}
RECEIPT_TOP_FIELDS = {
    "artifact_type",
    "artifacts",
    "checks",
    "finalizer_source_provenance",
    "gpu_run_summary",
    "implementation",
    "kernel_root",
    "payload_without_self_hash_sha256",
    "pre_execution_witness",
    "probe",
    "scheduler",
    "scheduler_amendment",
    "scheduler_final_envelope",
    "schema_version",
    "source",
}
SCHEDULER_RECEIPT_FIELDS = {
    "account",
    "comment",
    "elapsed_seconds",
    "end_time",
    "exit_code",
    "job_id",
    "job_name",
    "qos",
    "start_time",
    "state",
    "submit_time",
    "submitted_batch_script_sha256",
    "time_limit",
    "time_limit_minutes",
}
ENVELOPE_CHECK_FIELDS = {
    "final_qos_observed",
    "final_time_limit_observed",
    "gpu_job_had_never_started",
    "gpu_job_pending",
    "kernel_log_absent",
    "kernel_result_absent",
    "kernel_validation_absent",
    "pre_execution_witness_unchanged",
    "scheduler_amendment_unchanged",
    "submitted_batch_script_unchanged",
}
ENVELOPE_JOB_FIELDS = {
    "account",
    "command",
    "comment",
    "job_id",
    "job_name",
    "qos",
    "reason",
    "run_time",
    "start_time",
    "state",
    "stdout",
    "submit_time",
    "submitted_batch_script_sha256",
    "time_limit",
    "time_limit_minutes",
}


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def implementation_identity(path: Path = Path(__file__)) -> dict[str, Any]:
    identity = file_identity(path)
    return {
        "repository_path": IMPLEMENTATION_REPOSITORY_PATH,
        "size_bytes": identity["size_bytes"],
        "sha256": identity["sha256"],
    }


def _require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _read_canonical_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key in {resolved}: {key!r}")
            value[key] = item
        return value

    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {resolved}")
    if raw != canonical_json_bytes(payload):
        raise ValueError(f"JSON is not canonical: {resolved}")
    return raw, payload


def _parse_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value or value == "Unknown":
        raise ValueError(f"{name} is not a concrete UTC timestamp")
    parsed = datetime.fromisoformat(value.removesuffix("Z")).replace(tzinfo=UTC)
    return parsed


def _canonical_utc(value: str, name: str) -> str:
    return _parse_utc(value, name).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity_matches(recorded: object, path: Path, name: str) -> dict[str, Any]:
    record = _require_dict(recorded, name)
    actual = file_identity(path)
    if record != actual:
        raise ValueError(f"{name} differs from the current artifact: {path}")
    return actual


def _require_production_root(kernel_root: Path) -> Path:
    root = kernel_root.expanduser().resolve()
    if root != PRODUCTION_KERNEL_ROOT:
        raise ValueError(f"Kernel root must be the fixed production root {PRODUCTION_KERNEL_ROOT}")
    return root


def validate_witness(kernel_root: Path) -> dict[str, Any]:
    root = _require_production_root(kernel_root)
    path = root / WITNESS_NAME
    raw, witness = _read_canonical_json(path)
    identity = file_identity(path)
    if identity != {
        "path": str(path),
        "size_bytes": PRODUCTION_WITNESS_SIZE_BYTES,
        "sha256": PRODUCTION_WITNESS_SHA256,
    }:
        raise ValueError("Pre-execution witness identity differs from the fixed production witness")
    if stat.S_IMODE(path.stat().st_mode) & 0o222:
        raise ValueError("Pre-execution witness is writable")
    if len(raw) != PRODUCTION_WITNESS_SIZE_BYTES:
        raise RuntimeError("Witness byte count changed while reading")
    if set(witness) != WITNESS_TOP_FIELDS:
        raise ValueError("Pre-execution witness has the wrong top-level schema")
    if witness.get("schema_version") != SCHEMA_VERSION or witness.get("artifact_type") != WITNESS_ARTIFACT_TYPE:
        raise ValueError("Pre-execution witness has the wrong schema or artifact type")
    checks = _require_dict(witness.get("checks"), "witness.checks")
    if set(checks) != WITNESS_CHECK_FIELDS or any(value is not True for value in checks.values()):
        raise ValueError("Pre-execution witness checks are not exactly the fixed all-true inventory")

    outputs = _require_dict(witness.get("output_paths"), "witness.output_paths")
    expected_outputs = {
        "kernel_log": str(root / "logs" / f"kernel_{GPU_JOB_ID}.log"),
        "kernel_result": str(root / KERNEL_RESULT_NAME),
        "kernel_validation": str(root / KERNEL_VALIDATION_NAME),
    }
    if outputs != expected_outputs:
        raise ValueError("Pre-execution witness output paths differ from the production paths")

    gpu = _require_dict(witness.get("gpu_job"), "witness.gpu_job")
    expected_gpu = {
        "job_id": GPU_JOB_ID,
        "job_name": GPU_JOB_NAME,
        "state": "PENDING",
        "run_time": "00:00:00",
        "start_time": "Unknown",
        "qos": GPU_SUBMIT_QOS,
        "account": ACCOUNT,
        "stdout": expected_outputs["kernel_log"],
        "command": str(root / "source_snapshot/user/tianhaowu/rsci/scripts/run_known_cost_tag_kernel.sbatch"),
    }
    for key, expected in expected_gpu.items():
        if gpu.get(key) != expected:
            raise ValueError(f"Pre-execution witness GPU {key} differs from {expected!r}")
    observed_at = _parse_utc(witness.get("observed_at"), "witness.observed_at")
    submit_time = _parse_utc(gpu.get("submit_time"), "witness.gpu_job.submit_time")
    if observed_at <= submit_time:
        raise ValueError("Pre-execution witness was not observed after GPU submission")

    validator = _require_dict(witness.get("validator_job"), "witness.validator_job")
    expected_validator = {
        "job_id": VALIDATOR_JOB_ID,
        "job_name": VALIDATOR_JOB_NAME,
        "state": "PENDING",
        "qos": VALIDATOR_QOS,
        "command": str(root / "validate_kernel_result.sbatch"),
    }
    for key, expected in expected_validator.items():
        if validator.get(key) != expected:
            raise ValueError(f"Pre-execution witness validator {key} differs from {expected!r}")
    if validator.get("dependency") != f"afterany:{GPU_JOB_ID}(unfulfilled)":
        raise ValueError("Pre-execution witness validator dependency differs")
    validator_submit = _parse_utc(validator.get("submit_time"), "witness.validator_job.submit_time")
    if not submit_time <= validator_submit < observed_at:
        raise ValueError("Pre-execution witness validator submission time is inconsistent")

    probe = _require_dict(witness.get("probe"), "witness.probe")
    _identity_matches(probe.get("dataset"), root / "probe/probe_dataset.jsonl", "witness probe dataset")
    _identity_matches(probe.get("manifest"), root / "probe/probe_manifest.json", "witness probe manifest")
    source = _require_dict(witness.get("source"), "witness.source")
    _identity_matches(
        source.get("provenance_manifest"),
        root / source_provenance.MANIFEST_NAME,
        "witness source provenance",
    )
    _identity_matches(
        source.get("runner"),
        root / "source_snapshot/user/tianhaowu/rsci/scripts/run_known_cost_tag_kernel.sbatch",
        "witness runner",
    )
    _identity_matches(
        validator.get("script"),
        root / "validate_kernel_result.sbatch",
        "witness validator script",
    )
    return {"identity": identity, "witness": witness}


def validate_scheduler_amendment(
    kernel_root: Path,
    witness_record: dict[str, Any],
) -> dict[str, Any]:
    root = _require_production_root(kernel_root)
    path = root / AMENDMENT_NAME
    _, amendment = _read_canonical_json(path)
    identity = file_identity(path)
    if identity != {
        "path": str(path),
        "size_bytes": PRODUCTION_AMENDMENT_SIZE_BYTES,
        "sha256": PRODUCTION_AMENDMENT_SHA256,
    }:
        raise ValueError("Scheduler amendment identity differs from the fixed production amendment")
    if stat.S_IMODE(path.stat().st_mode) & 0o222:
        raise ValueError("Scheduler amendment is writable")
    expected_fields = {
        "artifact_type",
        "checks",
        "job_id",
        "new_scheduler_state",
        "observed_at",
        "old_scheduler_state",
        "pre_execution_witness",
        "rationale",
        "schema_version",
    }
    if set(amendment) != expected_fields:
        raise ValueError("Scheduler amendment has the wrong top-level schema")
    if amendment.get("schema_version") != SCHEMA_VERSION or amendment.get("artifact_type") != AMENDMENT_ARTIFACT_TYPE:
        raise ValueError("Scheduler amendment has the wrong schema or artifact type")
    checks = _require_dict(amendment.get("checks"), "amendment.checks")
    if not checks or any(value is not True for value in checks.values()):
        raise ValueError("Scheduler amendment checks are not all exactly true")
    if amendment.get("job_id") != GPU_JOB_ID:
        raise ValueError("Scheduler amendment names the wrong GPU job")
    if amendment.get("pre_execution_witness") != witness_record["identity"]:
        raise ValueError("Scheduler amendment binds a different pre-execution witness")
    expected_old = {
        "qos": "h100_lowest",
        "state": "PENDING",
        "reason": "Priority",
        "run_time": "00:00:00",
        "start_time": "Unknown",
        "priority": 100035,
    }
    expected_new = {
        "qos": GPU_FINAL_QOS,
        "state": "PENDING",
        "reason": "None",
        "run_time": "00:00:00",
        "start_time": "Unknown",
        "priority": 10000008,
    }
    if amendment.get("old_scheduler_state") != expected_old or amendment.get("new_scheduler_state") != expected_new:
        raise ValueError("Scheduler amendment old/new state differs from the fixed production transition")
    witness_time = _parse_utc(witness_record["witness"].get("observed_at"), "witness.observed_at")
    amendment_time = _parse_utc(amendment.get("observed_at"), "amendment.observed_at")
    if amendment_time <= witness_time:
        raise ValueError("Scheduler amendment was not observed after the pre-execution witness")
    return {"identity": identity, "amendment": amendment}


def validate_scheduler_final_envelope(
    kernel_root: Path,
    witness_record: dict[str, Any],
    amendment_record: dict[str, Any],
) -> dict[str, Any]:
    root = _require_production_root(kernel_root)
    path = root / ENVELOPE_NAME
    _, envelope = _read_canonical_json(path)
    identity = file_identity(path)
    if identity != {
        "path": str(path),
        "size_bytes": PRODUCTION_ENVELOPE_SIZE_BYTES,
        "sha256": PRODUCTION_ENVELOPE_SHA256,
    }:
        raise ValueError("Scheduler final envelope identity differs from the fixed production envelope")
    if stat.S_IMODE(path.stat().st_mode) & 0o222:
        raise ValueError("Scheduler final envelope is writable")
    expected_fields = {
        "artifact_type",
        "checks",
        "job",
        "observed_at",
        "pre_execution_witness",
        "scheduler_amendment",
        "schema_version",
    }
    if set(envelope) != expected_fields:
        raise ValueError("Scheduler final envelope has the wrong top-level schema")
    if envelope.get("schema_version") != SCHEMA_VERSION or envelope.get("artifact_type") != ENVELOPE_ARTIFACT_TYPE:
        raise ValueError("Scheduler final envelope has the wrong schema or artifact type")
    checks = _require_dict(envelope.get("checks"), "envelope.checks")
    if set(checks) != ENVELOPE_CHECK_FIELDS or any(value is not True for value in checks.values()):
        raise ValueError("Scheduler final envelope checks are not the exact all-true inventory")
    if envelope.get("pre_execution_witness") != witness_record["identity"]:
        raise ValueError("Scheduler final envelope binds a different pre-execution witness")
    if envelope.get("scheduler_amendment") != amendment_record["identity"]:
        raise ValueError("Scheduler final envelope binds a different scheduler amendment")
    witness = witness_record["witness"]
    witness_gpu = _require_dict(witness.get("gpu_job"), "witness.gpu_job")
    witness_source = _require_dict(witness.get("source"), "witness.source")
    expected_job = {
        "account": ACCOUNT,
        "command": witness_gpu["command"],
        "comment": witness_gpu["comment"],
        "job_id": GPU_JOB_ID,
        "job_name": GPU_JOB_NAME,
        "qos": GPU_FINAL_QOS,
        "reason": "Priority",
        "run_time": "00:00:00",
        "start_time": "Unknown",
        "state": "PENDING",
        "stdout": witness_gpu["stdout"],
        "submit_time": witness_gpu["submit_time"],
        "submitted_batch_script_sha256": _require_dict(witness_source["runner"], "witness runner")["sha256"],
        "time_limit": "00:45:00",
        "time_limit_minutes": 45,
    }
    job = _require_dict(envelope.get("job"), "envelope.job")
    if set(job) != ENVELOPE_JOB_FIELDS or job != expected_job:
        raise ValueError("Scheduler final envelope job differs from the fixed pre-execution state")
    witness_time = _parse_utc(witness.get("observed_at"), "witness.observed_at")
    amendment_time = _parse_utc(amendment_record["amendment"].get("observed_at"), "amendment.observed_at")
    envelope_time = _parse_utc(envelope.get("observed_at"), "envelope.observed_at")
    if not witness_time < amendment_time < envelope_time:
        raise ValueError("Scheduler final envelope chronology contradicts the witness or amendment")
    return {"identity": identity, "envelope": envelope}


def _source_record(kernel_root: Path) -> dict[str, Any]:
    state = source_provenance.verify_snapshot(
        kernel_root,
        verify_imports=False,
        require_launch=False,
    )
    manifest_path = kernel_root / source_provenance.MANIFEST_NAME
    _, manifest = _read_canonical_json(manifest_path)
    return {
        "manifest": file_identity(manifest_path),
        "parent_commit_sha": state["parent_commit_sha"],
        "source_tree_sha256": state["source_tree_sha256"],
        "uv_lock_sha256": manifest["uv_lock_sha256"],
        "pip_freeze_sha256": manifest["pip_freeze_sha256"],
        "environment": manifest["environment"],
    }


def finalizer_source_provenance() -> dict[str, Any]:
    root = CONTROL_PLANE_SOURCE_ROOT.resolve()
    state = source_provenance.verify_snapshot(
        root,
        verify_imports=True,
        require_launch=False,
    )
    snapshot = Path(str(state["snapshot_path"])).resolve()
    expected_implementation = snapshot / IMPLEMENTATION_REPOSITORY_PATH
    if Path(__file__).resolve() != expected_implementation:
        raise ValueError(f"Kernel finalizer must run from the pinned control-plane snapshot: {expected_implementation}")
    manifest_path = root / source_provenance.MANIFEST_NAME
    _, manifest = _read_canonical_json(manifest_path)
    runtime_identity = {
        "parent_commit_sha": state["parent_commit_sha"],
        "source_tree_sha256": state["source_tree_sha256"],
        "uv_lock_sha256": manifest["uv_lock_sha256"],
        "pip_freeze_sha256": manifest["pip_freeze_sha256"],
        "environment": manifest["environment"],
    }
    return {
        "manifest": file_identity(manifest_path),
        "environment_freeze": file_identity(root / source_provenance.FREEZE_NAME),
        "snapshot_path": str(snapshot),
        **runtime_identity,
        "runtime_identity_sha256": canonical_json_sha256(runtime_identity),
        "runtime_imports": state["runtime_imports"],
        "runtime_imports_sha256": canonical_json_sha256(state["runtime_imports"]),
    }


def _runtime_environment(snapshot: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "UV_NO_SYNC": "1",
            "PYTHONPATH": os.pathsep.join(str(snapshot / path) for path in source_provenance.RUNTIME_PATHS),
        }
    )
    shared_environment = snapshot / ".venv"
    if shared_environment.exists():
        environment["UV_PROJECT_ENVIRONMENT"] = str(shared_environment.resolve())
    return environment


def _run_pinned_result_validator(kernel_root: Path) -> dict[str, Any]:
    snapshot = kernel_root / "source_snapshot"
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "user/tianhaowu/rsci/probe_known_cost_tag_kernel.py",
            "validate-result",
            "--probe-dir",
            str(kernel_root / "probe"),
            "--output",
            str(kernel_root / KERNEL_RESULT_NAME),
        ],
        cwd=snapshot,
        env=_runtime_environment(snapshot),
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(completed.stdout)
    if not isinstance(summary, dict) or summary.get("command") != "validate-result":
        raise ValueError("Pinned kernel validator did not return its validate-result summary")
    return summary


def _validated_kernel_artifacts(kernel_root: Path) -> dict[str, Any]:
    result_path = kernel_root / KERNEL_RESULT_NAME
    validation_path = kernel_root / KERNEL_VALIDATION_NAME
    _, result = _read_canonical_json(result_path)
    _, validation = _read_canonical_json(validation_path)
    result_identity = file_identity(result_path)
    validation_identity = file_identity(validation_path)
    if set(validation) != KERNEL_VALIDATION_FIELDS:
        raise ValueError("Kernel validation summary has the wrong exact schema")
    decision = _require_dict(result.get("decision"), "kernel result decision")
    summary = _require_dict(result.get("kernel_summary"), "kernel result summary")
    expected_validation = {
        "command": "validate-result",
        "eligible_design": decision.get("eligible_design"),
        "finite_step_ordering_passed": decision.get("finite_step_ordering_passed"),
        "median_off_diagonal": summary.get("median_off_diagonal"),
        "output": str(result_path),
        "output_sha256": result_identity["sha256"],
    }
    if validation != expected_validation:
        raise ValueError("Kernel validation summary differs from the kernel result")
    pinned_summary = _run_pinned_result_validator(kernel_root)
    if pinned_summary != validation:
        raise ValueError("Current pinned static validation differs from the watcher validation")
    return {
        "result": result,
        "result_identity": result_identity,
        "validation": validation,
        "validation_identity": validation_identity,
    }


def parse_final_run_summary(log_path: Path, kernel_result: dict[str, Any]) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("command") == "run" and not text[end:].strip():
            candidates.append(value)
    if len(candidates) != 1:
        raise ValueError("GPU log must end in exactly one parseable kernel run summary")
    summary = candidates[0]
    result_path = log_path.parents[1] / KERNEL_RESULT_NAME
    result_identity = file_identity(result_path)
    if summary.get("output") != str(result_path):
        raise ValueError("GPU log run summary names the wrong kernel output path")
    if summary.get("output_sha256") != result_identity["sha256"]:
        raise ValueError("GPU log run summary names the wrong kernel output SHA-256")
    if summary.get("already_complete") is not False:
        raise ValueError("GPU log does not prove that the kernel result was freshly generated")
    for key in ("kernel", "kernel_orientation"):
        if summary.get(key) != kernel_result.get(key):
            raise ValueError(f"GPU log run summary {key} differs from the kernel result")
    decision = _require_dict(kernel_result.get("decision"), "kernel result decision")
    result_summary = _require_dict(kernel_result.get("kernel_summary"), "kernel result summary")
    expected = {
        "eligible_design": decision.get("eligible_design"),
        "finite_step_ordering_passed": decision.get("finite_step_ordering_passed"),
        "median_off_diagonal": result_summary.get("median_off_diagonal"),
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ValueError(f"GPU log run summary {key} differs from the kernel result")
    return {
        "canonical_summary_sha256": canonical_json_sha256(summary),
        "command": "run",
        "output": str(result_path),
        "output_sha256": result_identity["sha256"],
        "already_complete": False,
        **expected,
    }


def _sacct_job(job_id: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "sacct",
            "-j",
            job_id,
            "-X",
            "-n",
            "-P",
            "-o",
            ",".join(SACCT_FIELDS),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    rows = [line.split("|") for line in completed.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != len(SACCT_FIELDS):
        raise ValueError(f"sacct returned an ambiguous record for job {job_id}: {completed.stdout!r}")
    record = dict(zip(SACCT_FIELDS, rows[0], strict=True))
    if record["JobIDRaw"] != job_id:
        raise ValueError(f"sacct returned the wrong job id for {job_id}")
    return record


def _submitted_script_sha256(job_id: str) -> str:
    completed = subprocess.run(
        ["scontrol", "write", "batch_script", job_id, "-"],
        capture_output=True,
        check=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def _completed_scheduler_record(
    raw: dict[str, Any],
    *,
    expected_name: str,
    expected_qos: str,
    require_positive_elapsed: bool,
) -> dict[str, Any]:
    if raw["JobName"] != expected_name or raw["QOS"] != expected_qos or raw["Account"] != ACCOUNT:
        raise ValueError(f"Completed Slurm job identity differs for {raw['JobIDRaw']}")
    if raw["State"] != "COMPLETED" or raw["ExitCode"] != "0:0":
        raise ValueError(f"Slurm job {raw['JobIDRaw']} did not complete with exit code 0:0")
    try:
        elapsed_seconds = int(raw["ElapsedRaw"])
        time_limit_minutes = int(raw["TimelimitRaw"])
    except ValueError as error:
        raise ValueError(f"Slurm job {raw['JobIDRaw']} has invalid elapsed or time-limit fields") from error
    if elapsed_seconds < int(require_positive_elapsed):
        raise ValueError(f"Slurm job {raw['JobIDRaw']} has no positive runtime")
    if time_limit_minutes <= 0 or not raw["Timelimit"]:
        raise ValueError(f"Slurm job {raw['JobIDRaw']} has an invalid time limit")
    return {
        "job_id": raw["JobIDRaw"],
        "job_name": raw["JobName"],
        "state": raw["State"],
        "exit_code": raw["ExitCode"],
        "submit_time": _canonical_utc(raw["Submit"], f"job {raw['JobIDRaw']} submit"),
        "start_time": _canonical_utc(raw["Start"], f"job {raw['JobIDRaw']} start"),
        "end_time": _canonical_utc(raw["End"], f"job {raw['JobIDRaw']} end"),
        "elapsed_seconds": elapsed_seconds,
        "qos": raw["QOS"],
        "account": raw["Account"],
        "comment": raw["Comment"],
        "time_limit": raw["Timelimit"],
        "time_limit_minutes": time_limit_minutes,
    }


def _validate_scheduler_chronology(
    witness: dict[str, Any],
    amendment: dict[str, Any],
    final_envelope: dict[str, Any],
    gpu: dict[str, Any],
    validator: dict[str, Any],
) -> None:
    witness_gpu = _require_dict(witness.get("gpu_job"), "witness.gpu_job")
    witness_validator = _require_dict(witness.get("validator_job"), "witness.validator_job")
    if gpu["submit_time"] != witness_gpu.get("submit_time"):
        raise ValueError("Completed GPU job submit time differs from the pre-execution witness")
    if validator["submit_time"] != witness_validator.get("submit_time"):
        raise ValueError("Completed validator job submit time differs from the pre-execution witness")
    observed = _parse_utc(witness.get("observed_at"), "witness.observed_at")
    amended = _parse_utc(amendment.get("observed_at"), "amendment.observed_at")
    envelope_observed = _parse_utc(final_envelope.get("observed_at"), "final_envelope.observed_at")
    gpu_start = _parse_utc(gpu["start_time"], "GPU start")
    gpu_end = _parse_utc(gpu["end_time"], "GPU end")
    validator_start = _parse_utc(validator["start_time"], "validator start")
    validator_end = _parse_utc(validator["end_time"], "validator end")
    if not observed < amended < envelope_observed < gpu_start < gpu_end <= validator_start <= validator_end:
        raise ValueError(
            "Kernel GPU/validator chronology contradicts the pre-execution witness, scheduler envelope, or dependency"
        )
    envelope_job = _require_dict(final_envelope.get("job"), "final_envelope.job")
    if gpu["time_limit"] != envelope_job.get("time_limit") or gpu["time_limit_minutes"] != envelope_job.get(
        "time_limit_minutes"
    ):
        raise ValueError("Completed GPU job time limit differs from the sealed final scheduler envelope")


def _receipt_payload(kernel_root: Path) -> dict[str, Any]:
    witness_record = validate_witness(kernel_root)
    amendment_record = validate_scheduler_amendment(kernel_root, witness_record)
    envelope_record = validate_scheduler_final_envelope(kernel_root, witness_record, amendment_record)
    witness = witness_record["witness"]
    finalizer_source = finalizer_source_provenance()
    source = _source_record(kernel_root)
    artifacts = _validated_kernel_artifacts(kernel_root)
    log_path = kernel_root / "logs" / f"kernel_{GPU_JOB_ID}.log"
    run_summary = parse_final_run_summary(log_path, artifacts["result"])

    gpu = _completed_scheduler_record(
        _sacct_job(GPU_JOB_ID),
        expected_name=GPU_JOB_NAME,
        expected_qos=GPU_FINAL_QOS,
        require_positive_elapsed=True,
    )
    validator = _completed_scheduler_record(
        _sacct_job(VALIDATOR_JOB_ID),
        expected_name=VALIDATOR_JOB_NAME,
        expected_qos=VALIDATOR_QOS,
        require_positive_elapsed=False,
    )
    _validate_scheduler_chronology(
        witness,
        amendment_record["amendment"],
        envelope_record["envelope"],
        gpu,
        validator,
    )
    witness_source = _require_dict(witness["source"], "witness.source")
    witness_validator = _require_dict(witness["validator_job"], "witness.validator_job")
    gpu_script_sha = _submitted_script_sha256(GPU_JOB_ID)
    validator_script_sha = _submitted_script_sha256(VALIDATOR_JOB_ID)
    if gpu_script_sha != _require_dict(witness_source["runner"], "witness runner")["sha256"]:
        raise ValueError("Submitted GPU batch script differs from the witnessed runner")
    if validator_script_sha != _require_dict(witness_validator["script"], "witness validator script")["sha256"]:
        raise ValueError("Submitted validator batch script differs from the witnessed script")

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "kernel_root": str(kernel_root),
        "pre_execution_witness": witness_record["identity"],
        "scheduler_amendment": amendment_record["identity"],
        "scheduler_final_envelope": envelope_record["identity"],
        "finalizer_source_provenance": finalizer_source,
        "source": source,
        "probe": {
            "dataset": file_identity(kernel_root / "probe/probe_dataset.jsonl"),
            "manifest": file_identity(kernel_root / "probe/probe_manifest.json"),
        },
        "scheduler": {
            "gpu_job": {**gpu, "submitted_batch_script_sha256": gpu_script_sha},
            "validator_job": {
                **validator,
                "submitted_batch_script_sha256": validator_script_sha,
            },
        },
        "artifacts": {
            "gpu_log": file_identity(log_path),
            "kernel_result": artifacts["result_identity"],
            "kernel_validation": artifacts["validation_identity"],
            "validator_script": file_identity(kernel_root / "validate_kernel_result.sbatch"),
        },
        "gpu_run_summary": run_summary,
        "implementation": implementation_identity(),
        "checks": {name: True for name in sorted(RECEIPT_CHECK_FIELDS)},
    }
    receipt["payload_without_self_hash_sha256"] = canonical_json_sha256(receipt)
    return receipt


def _static_receipt_payload(receipt: dict[str, Any], kernel_root: Path) -> dict[str, Any]:
    witness_record = validate_witness(kernel_root)
    amendment_record = validate_scheduler_amendment(kernel_root, witness_record)
    envelope_record = validate_scheduler_final_envelope(kernel_root, witness_record, amendment_record)
    if receipt.get("pre_execution_witness") != witness_record["identity"]:
        raise ValueError("Receipt binds a different pre-execution witness")
    if receipt.get("scheduler_amendment") != amendment_record["identity"]:
        raise ValueError("Receipt binds a different scheduler amendment")
    if receipt.get("scheduler_final_envelope") != envelope_record["identity"]:
        raise ValueError("Receipt binds a different scheduler final envelope")
    if receipt.get("finalizer_source_provenance") != finalizer_source_provenance():
        raise ValueError("Receipt finalizer source provenance differs from the pinned control plane")
    if receipt.get("source") != _source_record(kernel_root):
        raise ValueError("Receipt source identity differs from the current sealed source")
    expected_probe = {
        "dataset": file_identity(kernel_root / "probe/probe_dataset.jsonl"),
        "manifest": file_identity(kernel_root / "probe/probe_manifest.json"),
    }
    if receipt.get("probe") != expected_probe:
        raise ValueError("Receipt probe identities differ from the current probe")
    artifacts = _validated_kernel_artifacts(kernel_root)
    log_path = kernel_root / "logs" / f"kernel_{GPU_JOB_ID}.log"
    expected_artifacts = {
        "gpu_log": file_identity(log_path),
        "kernel_result": artifacts["result_identity"],
        "kernel_validation": artifacts["validation_identity"],
        "validator_script": file_identity(kernel_root / "validate_kernel_result.sbatch"),
    }
    if receipt.get("artifacts") != expected_artifacts:
        raise ValueError("Receipt kernel/log/validator identities differ from current artifacts")
    if receipt.get("gpu_run_summary") != parse_final_run_summary(log_path, artifacts["result"]):
        raise ValueError("Receipt GPU run summary differs from the current log")
    if receipt.get("implementation") != implementation_identity():
        raise ValueError("Receipt finalizer implementation identity differs")

    scheduler = _require_dict(receipt.get("scheduler"), "receipt.scheduler")
    gpu = _require_dict(scheduler.get("gpu_job"), "receipt.scheduler.gpu_job")
    validator = _require_dict(scheduler.get("validator_job"), "receipt.scheduler.validator_job")
    for record, job_id, name, qos, require_elapsed in (
        (gpu, GPU_JOB_ID, GPU_JOB_NAME, GPU_FINAL_QOS, True),
        (validator, VALIDATOR_JOB_ID, VALIDATOR_JOB_NAME, VALIDATOR_QOS, False),
    ):
        if set(record) != SCHEDULER_RECEIPT_FIELDS:
            raise ValueError(f"Receipt scheduler {job_id} has the wrong exact field inventory")
        expected = {
            "job_id": job_id,
            "job_name": name,
            "state": "COMPLETED",
            "exit_code": "0:0",
            "qos": qos,
            "account": ACCOUNT,
        }
        for key, value in expected.items():
            if record.get(key) != value:
                raise ValueError(f"Receipt scheduler {job_id} {key} differs")
        elapsed = record.get("elapsed_seconds")
        if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < int(require_elapsed):
            raise ValueError(f"Receipt scheduler {job_id} elapsed time is invalid")
        time_limit = record.get("time_limit")
        time_limit_minutes = record.get("time_limit_minutes")
        if not isinstance(time_limit, str) or not time_limit:
            raise ValueError(f"Receipt scheduler {job_id} time limit is invalid")
        if isinstance(time_limit_minutes, bool) or not isinstance(time_limit_minutes, int) or time_limit_minutes <= 0:
            raise ValueError(f"Receipt scheduler {job_id} time-limit minutes are invalid")
    witness = witness_record["witness"]
    _validate_scheduler_chronology(
        witness,
        amendment_record["amendment"],
        envelope_record["envelope"],
        gpu,
        validator,
    )
    witness_source = _require_dict(witness["source"], "witness.source")
    witness_validator = _require_dict(witness["validator_job"], "witness.validator_job")
    if gpu.get("submitted_batch_script_sha256") != _require_dict(witness_source["runner"], "runner")["sha256"]:
        raise ValueError("Receipt GPU submitted script hash differs from the witness")
    if (
        validator.get("submitted_batch_script_sha256")
        != _require_dict(witness_validator["script"], "validator script")["sha256"]
    ):
        raise ValueError("Receipt validator submitted script hash differs from the witness")
    checks = _require_dict(receipt.get("checks"), "receipt.checks")
    if set(checks) != RECEIPT_CHECK_FIELDS or any(value is not True for value in checks.values()):
        raise ValueError("Receipt checks are not the exact all-true inventory")
    return receipt


def verify_receipt_scheduler(receipt: dict[str, Any]) -> dict[str, Any]:
    expected = {}
    for key, job_id, name, qos, require_elapsed in (
        ("gpu_job", GPU_JOB_ID, GPU_JOB_NAME, GPU_FINAL_QOS, True),
        ("validator_job", VALIDATOR_JOB_ID, VALIDATOR_JOB_NAME, VALIDATOR_QOS, False),
    ):
        record = _completed_scheduler_record(
            _sacct_job(job_id),
            expected_name=name,
            expected_qos=qos,
            require_positive_elapsed=require_elapsed,
        )
        expected[key] = {
            **record,
            "submitted_batch_script_sha256": _submitted_script_sha256(job_id),
        }
    if receipt.get("scheduler") != expected:
        raise ValueError("Kernel execution receipt scheduler identity differs from the live Slurm records")
    return expected


def write_receipt_once(path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path != PRODUCTION_KERNEL_ROOT / RECEIPT_NAME:
        raise ValueError(f"Kernel receipt must be written at {PRODUCTION_KERNEL_ROOT / RECEIPT_NAME}")
    content = canonical_json_bytes(receipt)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different kernel execution receipt: {path}")
            return file_identity(path)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".partial",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)
    return file_identity(path)


def build_receipt(kernel_root: Path) -> dict[str, Any]:
    root = _require_production_root(kernel_root)
    receipt = _receipt_payload(root)
    _static_receipt_payload(receipt, root)
    identity = write_receipt_once(root / RECEIPT_NAME, receipt)
    validated = validate_receipt(root / RECEIPT_NAME, verify_scheduler=True)
    if validated["identity"] != identity:
        raise RuntimeError("Kernel receipt identity changed during build and validation")
    return validated


def validate_receipt(path: Path, *, verify_scheduler: bool = False) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if resolved != PRODUCTION_KERNEL_ROOT / RECEIPT_NAME:
        raise ValueError(f"Kernel receipt must be at {PRODUCTION_KERNEL_ROOT / RECEIPT_NAME}")
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Kernel execution receipt is writable")
    raw, receipt = _read_canonical_json(resolved)
    if set(receipt) != RECEIPT_TOP_FIELDS:
        raise ValueError("Kernel execution receipt has the wrong exact top-level schema")
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Kernel execution receipt has the wrong schema or artifact type")
    if receipt.get("kernel_root") != str(PRODUCTION_KERNEL_ROOT):
        raise ValueError("Kernel execution receipt names the wrong kernel root")
    recorded_hash = receipt.get("payload_without_self_hash_sha256")
    payload = dict(receipt)
    payload.pop("payload_without_self_hash_sha256", None)
    if not isinstance(recorded_hash, str) or canonical_json_sha256(payload) != recorded_hash:
        raise ValueError("Kernel execution receipt self hash differs from its canonical payload")
    if raw != canonical_json_bytes(receipt):
        raise RuntimeError("Kernel execution receipt changed during static replay")
    _static_receipt_payload(receipt, PRODUCTION_KERNEL_ROOT)
    if verify_scheduler:
        verify_receipt_scheduler(receipt)
    return {"receipt": receipt, "identity": file_identity(resolved)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--kernel-root", type=Path, default=PRODUCTION_KERNEL_ROOT)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--receipt", type=Path, default=PRODUCTION_KERNEL_ROOT / RECEIPT_NAME)
    validate.add_argument("--verify-scheduler", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        result = build_receipt(args.kernel_root)
    else:
        result = validate_receipt(args.receipt, verify_scheduler=args.verify_scheduler)
    print(
        json.dumps(
            {
                "command": args.command,
                "receipt": result["identity"],
                "gpu_job_id": GPU_JOB_ID,
                "validator_job_id": VALIDATOR_JOB_ID,
                "eligible_design": result["receipt"]["gpu_run_summary"]["eligible_design"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
