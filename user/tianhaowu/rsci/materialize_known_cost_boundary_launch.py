#!/usr/bin/env python3
"""Materialize and replay the known-cost boundary RL submission intent."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import analyze_known_cost_boundary_preflight as preflight
import finalize_known_cost_kernel_execution as kernel_execution
import probe_known_cost_tag_kernel as kernel_probe
import source_provenance

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_boundary_submission_intent"
STUDY_ID = "verifier-defect-known-cost-boundary-v1"
INTENT_NAME = "submission_intent.json"
KERNEL_RECONCILIATION_NAME = "kernel_finalizer_reconciliation.json"
KERNEL_RECONCILIATION_ARTIFACT_TYPE = "rsci_known_cost_kernel_finalizer_reconciliation"
KERNEL_RECONCILIATION_TOP_FIELDS = {
    "artifact_type",
    "checks",
    "finalizer_evidence",
    "historical_receipt_replay",
    "implementation",
    "kernel_root",
    "payload_without_self_hash_sha256",
    "receipt",
    "scheduler",
    "schema_version",
    "source_provenance",
}
KERNEL_RECONCILIATION_CHECK_FIELDS = {
    "captured_finalizer_script_is_nonempty_read_only_and_within_controller_retention",
    "finalizer_allocation_completed_with_zero_exit",
    "finalizer_log_proves_live_receipt_build_and_scheduler_validation",
    "gpu_and_validator_terminal_sacct_match_receipt",
    "historical_finalizer_statically_replays_receipt",
    "receipt_submitted_script_hashes_match_pre_execution_witness",
}
FINALIZER_JOB_ID = "10281828"
FINALIZER_JOB_NAME = "rsci-kc-kernel-finalize-v1"
FINALIZER_QOS = "cpu_lowest"
FINALIZER_ACCOUNT = "ram"
FINALIZER_SCRIPT_NAME = "kernel_receipt_finalizer_submitted_10281828.sbatch"
FINALIZER_SCRIPT_SHA256 = "c35faf42798d619e14e4b7dbab9da388e84520f1ec25414a3f7c699ee6423111"
FINALIZER_SCRIPT_SIZE_BYTES = 1075
FINALIZER_LOG_PATH = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-control-plane-v1/logs/finalize_10281828.log"
)
FINALIZER_LOG_SHA256 = "b9ef805a0d6b2a919abaec6a37e7cb25374e4cbad68ca257ffdbb84039c384f2"
FINALIZER_LOG_SIZE_BYTES = 753
FINALIZER_STDIO_TEMPLATE = str(FINALIZER_LOG_PATH.with_name("finalize_%j.log"))
CONTROLLER_MIN_JOB_AGE_SECONDS = 600
SMOKE_ARM_FILENAMES = (
    "b20260808_g_p0125.toml",
    "b20260808_t_p0125.toml",
    "b20260808_g_p0375.toml",
    "b20260808_t_p0375.toml",
)
CONTROL_TMUX = {
    "socket": "/tmp/codex-rsci-control-20260806.sock",
    "session": "codex-rsci-control-20260806",
    "window": "Launcher",
}
MAX_ARMS_PER_DISPATCH = 5
REQUIRED_DISPATCH_QOS = "h100_ram_high"
REQUIRED_DISPATCH_STATE_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-v1"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
KERNEL_VALIDATION_FIELDS = {
    "command",
    "eligible_design",
    "finite_step_ordering_passed",
    "median_off_diagonal",
    "output",
    "output_sha256",
}

IMPLEMENTATION_REPOSITORY_PATHS = {
    "preflight": Path("user/tianhaowu/rsci/analyze_known_cost_boundary_preflight.py"),
    "runtime": Path("user/tianhaowu/rsci/rsci_gsm_infinite.py"),
    "tagged_bank_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_tagged_bank.py"),
    "post_run_replay": Path("user/tianhaowu/rsci/analyze_masked_verifier_attempts.py"),
    "source_provenance": Path("user/tianhaowu/rsci/source_provenance.py"),
    "strict_readout": Path("user/tianhaowu/rsci/figure3_eval.py"),
}
CONTROL_PLANE_REPOSITORY_PATHS = {
    "dispatcher": Path("user/tianhaowu/rsci/dispatch_known_cost_boundary.py"),
    "eval_planner": Path("user/tianhaowu/rsci/materialize_known_cost_eval_plan.py"),
    "kernel_execution_finalizer": Path("user/tianhaowu/rsci/finalize_known_cost_kernel_execution.py"),
    "kernel_probe": Path("user/tianhaowu/rsci/probe_known_cost_tag_kernel.py"),
    "launch_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py"),
    "known_cost_preflight": Path("user/tianhaowu/rsci/analyze_known_cost_boundary_preflight.py"),
    "postrun_authority_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_postrun_authority.py"),
    "promotion_authority_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_promotion.py"),
    "source_provenance": Path("user/tianhaowu/rsci/source_provenance.py"),
}


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"TOML root is not an object: {path}")
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
        raise ValueError(f"JSON artifact is not canonical: {resolved}")
    return raw, payload


def _repository_relative(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    parts = resolved.parts
    marker = ("user", "tianhaowu", "rsci")
    matches = [
        index for index in range(len(parts) - len(marker) + 1) if tuple(parts[index : index + len(marker)]) == marker
    ]
    if len(matches) != 1:
        raise ValueError(f"Cannot derive one repository-relative RSCI path from {resolved}")
    relative = Path(*parts[matches[0] :])
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"Unsafe repository-relative path: {relative}")
    return relative


def _source_root(path: Path) -> tuple[Path, Path]:
    resolved = path.expanduser().resolve()
    relative = _repository_relative(resolved)
    root = resolved
    for _ in relative.parts:
        root = root.parent
    if (root / relative).resolve() != resolved:
        raise ValueError(f"Cannot recover the source root for {resolved}")
    if not (root / "pyproject.toml").is_file() or not (root / "uv.lock").is_file():
        raise ValueError(f"Recorded implementation is not inside a prime-rl source tree: {resolved}")
    return root, relative


def _run_exact_validator(implementation: Path, arguments: list[str]) -> dict[str, Any]:
    source_root, relative = _source_root(implementation)
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "UV_NO_SYNC": "1",
            "PYTHONPATH": os.pathsep.join(str(source_root / item) for item in source_provenance.RUNTIME_PATHS),
        }
    )
    shared_environment = source_root / ".venv"
    if shared_environment.exists():
        environment["UV_PROJECT_ENVIRONMENT"] = str(shared_environment.resolve())
    completed = subprocess.run(
        ["uv", "run", "--no-sync", relative.as_posix(), *arguments],
        cwd=source_root,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(completed.stdout)
    if not isinstance(summary, dict):
        raise ValueError(f"Validator {implementation} did not return one JSON object")
    return summary


def _expected_arm_inventory() -> tuple[str, ...]:
    names = tuple(arm.filename for arm in preflight.arm_contracts())
    if len(names) != 30 or len(set(names)) != 30:
        raise RuntimeError("Known-cost preflight no longer declares exactly 30 unique arms")
    return names


def _source_provenance_record(root: Path, state: dict[str, Any]) -> dict[str, Any]:
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
        **runtime_identity,
        "runtime_identity_sha256": canonical_json_sha256(runtime_identity),
    }


def _control_plane_source_provenance() -> dict[str, Any]:
    snapshot, _ = _source_root(Path(__file__))
    control_root = snapshot.parent
    state = source_provenance.verify_snapshot(
        control_root,
        verify_imports=False,
        require_launch=False,
    )
    if Path(str(state["snapshot_path"])).resolve() != snapshot:
        raise ValueError("Launch materializer source differs from its control-plane snapshot")
    implementations = {
        name: file_identity(snapshot / relative) for name, relative in sorted(CONTROL_PLANE_REPOSITORY_PATHS.items())
    }
    imported = {
        "kernel_execution_finalizer": Path(kernel_execution.__file__).resolve(),
        "kernel_probe": Path(kernel_probe.__file__).resolve(),
        "launch_materializer": Path(__file__).resolve(),
        "known_cost_preflight": Path(preflight.__file__).resolve(),
        "source_provenance": Path(source_provenance.__file__).resolve(),
    }
    for name, current_path in imported.items():
        expected_path = snapshot / CONTROL_PLANE_REPOSITORY_PATHS[name]
        if current_path != expected_path:
            raise ValueError(f"{name} must be imported from the pinned control-plane snapshot: {expected_path}")
    return {
        **_source_provenance_record(control_root, state),
        "snapshot_path": str(snapshot),
        "implementations": implementations,
    }


def validate_control_plane_implementation(
    intent: dict[str, Any],
    *,
    name: str,
    implementation_path: Path,
) -> dict[str, Any]:
    if name not in CONTROL_PLANE_REPOSITORY_PATHS:
        raise ValueError(f"Unknown control-plane implementation: {name}")
    source = _require_dict(intent.get("control_plane_source"), "control_plane_source")
    implementations = _require_dict(source.get("implementations"), "control_plane implementations")
    if set(implementations) != set(CONTROL_PLANE_REPOSITORY_PATHS):
        raise ValueError("Launch intent has the wrong control-plane implementation inventory")
    expected = _require_dict(implementations.get(name), f"control-plane implementation {name}")
    current = file_identity(implementation_path)
    if current != expected:
        raise ValueError(f"{name} is not executing from the pinned control-plane snapshot")
    return current


def eligible_arm_filenames(kernel_result: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    decision = _require_dict(kernel_result.get("decision"), "kernel_result.decision")
    design = decision.get("eligible_design")
    full_grid = decision.get("full_grid_eligible")
    if design == "full_30_arm_grid" and full_grid is True:
        return design, _expected_arm_inventory()
    if design == "four_arm_smoke_screen" and full_grid is False:
        inventory = set(_expected_arm_inventory())
        if any(name not in inventory for name in SMOKE_ARM_FILENAMES):
            raise RuntimeError("The preregistered smoke arms are absent from the 30-arm inventory")
        return design, SMOKE_ARM_FILENAMES
    raise ValueError("Kernel decision is not one of the two preregistered eligible designs")


def _validated_preflight(report_path: Path, tokenizer_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    _, report = _read_canonical_json(report_path)
    identity = file_identity(report_path)
    if (
        report.get("schema_version") != preflight.SCHEMA_VERSION
        or report.get("artifact_type") != preflight.ARTIFACT_TYPE
    ):
        raise ValueError("Production preflight report has the wrong schema or artifact type")
    self_hash = _require_sha256(report.get("payload_without_self_hash_sha256"), "preflight self hash")
    payload = dict(report)
    payload.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(payload) != self_hash:
        raise ValueError("Preflight report self hash differs from its canonical payload")
    implementations = _require_dict(report.get("implementation_identities"), "preflight implementations")
    recorded_validator = _require_dict(implementations.get("preflight"), "preflight validator identity")
    validator_path = Path(str(recorded_validator.get("path"))).resolve()
    if _repository_relative(validator_path) != IMPLEMENTATION_REPOSITORY_PATHS["preflight"]:
        raise ValueError("Preflight report names the wrong validator implementation path")
    _identity_matches(recorded_validator, validator_path, "preflight validator")
    _identity_matches(recorded_validator, Path(preflight.__file__), "imported preflight dependency")
    recorded_provenance = _require_dict(
        implementations.get("source_provenance"),
        "preflight source_provenance identity",
    )
    _identity_matches(
        recorded_provenance,
        Path(source_provenance.__file__),
        "imported source_provenance dependency",
    )
    validation_summary = _run_exact_validator(
        validator_path,
        [
            "validate",
            "--report",
            str(report_path.expanduser().resolve()),
            "--tokenizer",
            str(tokenizer_path.expanduser().resolve()),
        ],
    )
    if validation_summary.get("command") != "validate":
        raise ValueError("Preflight validator did not execute its validate command")
    for key in ("path", "size_bytes", "sha256"):
        if validation_summary.get(key) != identity[key]:
            raise ValueError(f"Preflight validator returned a different report {key}")
    checks = _require_dict(report.get("checks"), "preflight checks")
    if not checks or any(value is not True for value in checks.values()):
        raise ValueError("Every production preflight check must be exactly true")
    config_audit = _require_dict(report.get("config_audit"), "preflight config_audit")
    arms = _require_dict(config_audit.get("arms"), "preflight config_audit.arms")
    expected = set(_expected_arm_inventory())
    if config_audit.get("arm_count") != 30 or set(arms) != expected:
        raise ValueError("Production preflight does not bind the exact frozen 30-arm inventory")
    preflight_root = report_path.expanduser().resolve().parent
    source_state = source_provenance.verify_snapshot(
        preflight_root,
        verify_imports=False,
        require_launch=False,
    )
    return report, {
        "report": identity,
        "payload_without_self_hash_sha256": self_hash,
        "checks": checks,
        "source_provenance": _source_provenance_record(preflight_root, source_state),
    }


def _optional_kernel_validation(
    path: Path | None,
    kernel_identity: dict[str, Any],
    kernel_result: dict[str, Any],
) -> dict[str, Any] | None:
    if path is None:
        return None
    path = path.expanduser().resolve()
    _, payload = _read_canonical_json(path)
    if set(payload) != KERNEL_VALIDATION_FIELDS:
        raise ValueError(f"{path} does not have the exact kernel validation summary schema")
    if payload.get("command") != "validate-result":
        raise ValueError(f"{path} did not record the kernel validate-result command")
    if Path(str(payload.get("output"))).expanduser().resolve() != Path(kernel_identity["path"]).resolve():
        raise ValueError(f"{path} does not reference the exact validated kernel result path")
    if payload.get("output_sha256") != kernel_identity["sha256"]:
        raise ValueError(f"{path} does not reference the validated kernel result SHA-256")
    decision = _require_dict(kernel_result.get("decision"), "kernel result decision")
    summary = _require_dict(kernel_result.get("kernel_summary"), "kernel result summary")
    expected = {
        "eligible_design": decision.get("eligible_design"),
        "finite_step_ordering_passed": decision.get("finite_step_ordering_passed"),
        "median_off_diagonal": summary.get("median_off_diagonal"),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"{path} {key} differs from the validated kernel result")
    return {
        "identity": file_identity(path),
        "payload_sha256": canonical_json_sha256(payload),
    }


def _validated_kernel_execution_receipt(
    receipt_path: Path,
    *,
    verify_scheduler: bool,
) -> dict[str, Any]:
    resolved = receipt_path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Kernel execution receipt is writable")
    raw_before, receipt = _read_canonical_json(resolved)
    if set(receipt) != kernel_execution.RECEIPT_TOP_FIELDS:
        raise ValueError("Kernel execution receipt has the wrong exact top-level schema")
    if (
        receipt.get("schema_version") != kernel_execution.SCHEMA_VERSION
        or receipt.get("artifact_type") != kernel_execution.ARTIFACT_TYPE
    ):
        raise ValueError("Kernel execution receipt has the wrong schema or artifact type")
    payload = dict(receipt)
    recorded_hash = payload.pop("payload_without_self_hash_sha256", None)
    if not isinstance(recorded_hash, str) or canonical_json_sha256(payload) != recorded_hash:
        raise ValueError("Kernel execution receipt self hash differs")

    source = _require_dict(receipt.get("finalizer_source_provenance"), "kernel finalizer source provenance")
    snapshot = Path(str(source.get("snapshot_path"))).expanduser().resolve()
    implementation = _require_dict(receipt.get("implementation"), "kernel finalizer implementation")
    repository_path = implementation.get("repository_path")
    if repository_path != kernel_execution.IMPLEMENTATION_REPOSITORY_PATH:
        raise ValueError("Kernel receipt records the wrong finalizer repository path")
    validator_path = snapshot / str(repository_path)
    if _repository_relative(validator_path) != CONTROL_PLANE_REPOSITORY_PATHS["kernel_execution_finalizer"]:
        raise ValueError("Kernel receipt records an unsafe finalizer path")
    validator_identity = file_identity(validator_path)
    if {
        "repository_path": repository_path,
        "size_bytes": validator_identity["size_bytes"],
        "sha256": validator_identity["sha256"],
    } != implementation:
        raise ValueError("Kernel receipt finalizer bytes differ from its recorded implementation")

    receipt_identity = file_identity(resolved)
    arguments = ["validate", "--receipt", str(resolved)]
    if verify_scheduler:
        arguments.append("--verify-scheduler")
    summary = _run_exact_validator(validator_path, arguments)
    scheduler = _require_dict(receipt.get("scheduler"), "kernel receipt scheduler")
    gpu = _require_dict(scheduler.get("gpu_job"), "kernel GPU scheduler record")
    validator = _require_dict(scheduler.get("validator_job"), "kernel validator scheduler record")
    run_summary = _require_dict(receipt.get("gpu_run_summary"), "kernel GPU run summary")
    expected_summary = {
        "command": "validate",
        "receipt": receipt_identity,
        "gpu_job_id": gpu.get("job_id"),
        "validator_job_id": validator.get("job_id"),
        "eligible_design": run_summary.get("eligible_design"),
    }
    if summary != expected_summary:
        raise ValueError("Recorded kernel finalizer returned a different validation summary")
    raw_after, replayed = _read_canonical_json(resolved)
    if raw_after != raw_before or replayed != receipt or file_identity(resolved) != receipt_identity:
        raise RuntimeError("Kernel execution receipt changed while its recorded finalizer validated it")
    return {
        "receipt": receipt,
        "identity": receipt_identity,
        "validator": {
            "repository_path": str(repository_path),
            **validator_identity,
        },
        "validator_source_provenance": source,
        "validation_summary_sha256": canonical_json_sha256(summary),
    }


def _without_submitted_script(record: dict[str, Any]) -> dict[str, Any]:
    durable = dict(record)
    script_sha = _require_sha256(
        durable.pop("submitted_batch_script_sha256", None),
        "receipt scheduler submitted_batch_script_sha256",
    )
    if script_sha == hashlib.sha256(b"").hexdigest():
        raise ValueError("Receipt scheduler submitted script cannot be the empty-output SHA-256")
    return durable


def _live_terminal_scheduler_records(receipt: dict[str, Any]) -> dict[str, Any]:
    scheduler = _require_dict(receipt.get("scheduler"), "kernel receipt scheduler")
    reconciled = {}
    for key, job_id, name, qos, require_elapsed in (
        (
            "gpu_job",
            kernel_execution.GPU_JOB_ID,
            kernel_execution.GPU_JOB_NAME,
            kernel_execution.GPU_FINAL_QOS,
            True,
        ),
        (
            "validator_job",
            kernel_execution.VALIDATOR_JOB_ID,
            kernel_execution.VALIDATOR_JOB_NAME,
            kernel_execution.VALIDATOR_QOS,
            False,
        ),
    ):
        recorded = _require_dict(scheduler.get(key), f"kernel receipt scheduler.{key}")
        expected = _without_submitted_script(recorded)
        actual = kernel_execution._completed_scheduler_record(
            kernel_execution._sacct_job(job_id),
            expected_name=name,
            expected_qos=qos,
            require_positive_elapsed=require_elapsed,
        )
        if actual != expected:
            raise ValueError(f"Kernel receipt {key} differs from live terminal sacct")
        reconciled[key] = actual
    return reconciled


def _sacct_finalizer_job() -> dict[str, Any]:
    fields = (*kernel_execution.SACCT_FIELDS, "StdOut", "StdErr")
    completed = subprocess.run(
        ["sacct", "-j", FINALIZER_JOB_ID, "-X", "-n", "-P", "-o", ",".join(fields)],
        text=True,
        capture_output=True,
        check=True,
    )
    rows = [line.split("|") for line in completed.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != len(fields):
        raise ValueError(
            f"sacct returned an ambiguous finalizer record for job {FINALIZER_JOB_ID}: {completed.stdout!r}"
        )
    raw = dict(zip(fields, rows[0], strict=True))
    if raw["JobIDRaw"] != FINALIZER_JOB_ID:
        raise ValueError("sacct returned the wrong finalizer job id")
    record = kernel_execution._completed_scheduler_record(
        raw,
        expected_name=FINALIZER_JOB_NAME,
        expected_qos=FINALIZER_QOS,
        require_positive_elapsed=True,
    )
    if record["account"] != FINALIZER_ACCOUNT:
        raise ValueError("Finalizer Slurm account differs")
    if record["comment"] != "" or record["time_limit"] != "00:30:00" or record["time_limit_minutes"] != 30:
        raise ValueError("Finalizer Slurm comment or time limit differs")
    if raw["StdOut"] != FINALIZER_STDIO_TEMPLATE or raw["StdErr"] != FINALIZER_STDIO_TEMPLATE:
        raise ValueError("Finalizer Slurm stdout/stderr template differs")
    return {
        **record,
        "stdout_template": raw["StdOut"],
        "stderr_template": raw["StdErr"],
    }


def _fixed_finalizer_script_identity(kernel_root: Path) -> dict[str, Any]:
    path = kernel_root / FINALIZER_SCRIPT_NAME
    identity = file_identity(path)
    expected = {
        "path": str(path),
        "size_bytes": FINALIZER_SCRIPT_SIZE_BYTES,
        "sha256": FINALIZER_SCRIPT_SHA256,
    }
    if identity != expected:
        raise ValueError("Captured finalizer submitted script differs from the fixed live capture")
    if stat.S_IMODE(path.stat().st_mode) & 0o222:
        raise ValueError("Captured finalizer submitted script is writable")
    return identity


def _fixed_finalizer_script_capture(
    kernel_root: Path,
    finalizer_job: dict[str, Any],
) -> dict[str, Any]:
    identity = _fixed_finalizer_script_identity(kernel_root)
    path = kernel_root / FINALIZER_SCRIPT_NAME
    if identity["size_bytes"] <= 0:
        raise ValueError("Captured finalizer submitted script is empty")
    mtime_ns = path.stat().st_mtime_ns
    mtime = datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC)
    finalizer_end = kernel_execution._parse_utc(finalizer_job.get("end_time"), "finalizer end")
    retention_deadline = finalizer_end + timedelta(seconds=CONTROLLER_MIN_JOB_AGE_SECONDS)
    if not finalizer_end <= mtime <= retention_deadline:
        raise ValueError("Finalizer script capture mtime falls outside controller retention")
    return {
        "capture_command": ["scontrol", "write", "batch_script", FINALIZER_JOB_ID, str(path)],
        "capture_mtime_ns": mtime_ns,
        "capture_mtime_utc": mtime.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "controller_min_job_age_seconds": CONTROLLER_MIN_JOB_AGE_SECONDS,
        "controller_retention_deadline_utc": retention_deadline.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "identity": identity,
        "nonempty_capture": True,
        "read_only_capture": True,
    }


def _json_stream(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    cursor = 0
    values = []
    while True:
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor == len(text):
            break
        value, cursor = decoder.raw_decode(text, cursor)
        values.append(_require_dict(value, f"JSON value {len(values)} in {path}"))
    return values


def _fixed_finalizer_log_evidence(
    receipt_identity: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    identity = file_identity(FINALIZER_LOG_PATH)
    expected_identity = {
        "path": str(FINALIZER_LOG_PATH),
        "size_bytes": FINALIZER_LOG_SIZE_BYTES,
        "sha256": FINALIZER_LOG_SHA256,
    }
    if identity != expected_identity:
        raise ValueError("Finalizer allocation log differs from the fixed successful log")
    if stat.S_IMODE(FINALIZER_LOG_PATH.stat().st_mode) & 0o222:
        raise ValueError("Finalizer allocation log is writable")
    scheduler = _require_dict(receipt.get("scheduler"), "kernel receipt scheduler")
    gpu = _require_dict(scheduler.get("gpu_job"), "kernel receipt GPU scheduler record")
    validator = _require_dict(scheduler.get("validator_job"), "kernel receipt validator scheduler record")
    run_summary = _require_dict(receipt.get("gpu_run_summary"), "kernel receipt GPU run summary")
    common = {
        "receipt": receipt_identity,
        "gpu_job_id": gpu.get("job_id"),
        "validator_job_id": validator.get("job_id"),
        "eligible_design": run_summary.get("eligible_design"),
    }
    expected_summaries = [
        {"command": "build", **common},
        {"command": "validate", **common},
    ]
    summaries = _json_stream(FINALIZER_LOG_PATH)
    if summaries != expected_summaries:
        raise ValueError("Finalizer allocation log does not contain the exact build/validate summaries")
    return {"identity": identity, "summaries": summaries}


def _receipt_mtime_evidence(
    receipt_path: Path,
    receipt: dict[str, Any],
    finalizer_job: dict[str, Any],
) -> dict[str, Any]:
    mtime_ns = receipt_path.stat().st_mtime_ns
    mtime = datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC)
    scheduler = _require_dict(receipt.get("scheduler"), "kernel receipt scheduler")
    gpu = _require_dict(scheduler.get("gpu_job"), "kernel receipt GPU scheduler record")
    validator = _require_dict(scheduler.get("validator_job"), "kernel receipt validator scheduler record")
    gpu_end = kernel_execution._parse_utc(gpu.get("end_time"), "GPU end")
    validator_end = kernel_execution._parse_utc(validator.get("end_time"), "validator end")
    finalizer_start = kernel_execution._parse_utc(finalizer_job.get("start_time"), "finalizer start")
    finalizer_end = kernel_execution._parse_utc(finalizer_job.get("end_time"), "finalizer end")
    if not gpu_end < validator_end < finalizer_start <= mtime <= finalizer_end:
        raise ValueError("Receipt mtime contradicts GPU, validator, or finalizer chronology")
    return {
        "mtime_ns": mtime_ns,
        "mtime_utc": mtime.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }


def _historical_receipt_replay_record(validated: dict[str, Any]) -> dict[str, Any]:
    return {
        "validator": validated["validator"],
        "validator_source_provenance": validated["validator_source_provenance"],
        "validation_summary_sha256": validated["validation_summary_sha256"],
    }


def _build_kernel_reconciliation(kernel_root: Path) -> dict[str, Any]:
    kernel_root = kernel_root.expanduser().resolve()
    receipt_path = kernel_root / kernel_execution.RECEIPT_NAME
    validated = _validated_kernel_execution_receipt(receipt_path, verify_scheduler=False)
    receipt = validated["receipt"]
    finalizer_job = _sacct_finalizer_job()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": KERNEL_RECONCILIATION_ARTIFACT_TYPE,
        "kernel_root": str(kernel_root),
        "receipt": validated["identity"],
        "historical_receipt_replay": _historical_receipt_replay_record(validated),
        "scheduler": {
            **_live_terminal_scheduler_records(receipt),
            "finalizer_job": finalizer_job,
        },
        "finalizer_evidence": {
            "submitted_script_capture": _fixed_finalizer_script_capture(kernel_root, finalizer_job),
            "allocation_log": _fixed_finalizer_log_evidence(validated["identity"], receipt),
            "receipt_mtime": _receipt_mtime_evidence(receipt_path, receipt, finalizer_job),
        },
        "source_provenance": _control_plane_source_provenance(),
        "implementation": file_identity(Path(__file__)),
        "checks": {name: True for name in sorted(KERNEL_RECONCILIATION_CHECK_FIELDS)},
    }
    payload["payload_without_self_hash_sha256"] = canonical_json_sha256(payload)
    return payload


def write_kernel_reconciliation_once(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = path.expanduser().resolve()
    expected_path = Path(str(payload.get("kernel_root"))).resolve() / KERNEL_RECONCILIATION_NAME
    if path != expected_path:
        raise ValueError(f"Kernel reconciliation must be adjacent to the kernel root at {expected_path}")
    content = canonical_json_bytes(payload)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different kernel reconciliation: {path}")
            return file_identity(path)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".partial")
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


def validate_kernel_reconciliation(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Kernel finalizer reconciliation is writable")
    raw, payload = _read_canonical_json(resolved)
    if set(payload) != KERNEL_RECONCILIATION_TOP_FIELDS:
        raise ValueError("Kernel finalizer reconciliation has the wrong exact top-level schema")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("artifact_type") != KERNEL_RECONCILIATION_ARTIFACT_TYPE
    ):
        raise ValueError("Kernel finalizer reconciliation has the wrong schema or artifact type")
    kernel_root = Path(str(payload.get("kernel_root"))).expanduser().resolve()
    if resolved != kernel_root / KERNEL_RECONCILIATION_NAME:
        raise ValueError("Kernel finalizer reconciliation is not adjacent to its kernel root")
    recorded_hash = payload.get("payload_without_self_hash_sha256")
    without_hash = dict(payload)
    without_hash.pop("payload_without_self_hash_sha256", None)
    if not isinstance(recorded_hash, str) or canonical_json_sha256(without_hash) != recorded_hash:
        raise ValueError("Kernel finalizer reconciliation self hash differs")
    receipt_path = kernel_root / kernel_execution.RECEIPT_NAME
    validated = _validated_kernel_execution_receipt(receipt_path, verify_scheduler=False)
    if payload.get("receipt") != validated["identity"]:
        raise ValueError("Kernel finalizer reconciliation binds a different receipt")
    if payload.get("historical_receipt_replay") != _historical_receipt_replay_record(validated):
        raise ValueError("Kernel finalizer reconciliation records a different historical receipt replay")
    receipt = validated["receipt"]
    scheduler = _require_dict(payload.get("scheduler"), "kernel reconciliation scheduler")
    receipt_scheduler = _require_dict(receipt.get("scheduler"), "kernel receipt scheduler")
    for key in ("gpu_job", "validator_job"):
        if scheduler.get(key) != _without_submitted_script(
            _require_dict(receipt_scheduler.get(key), f"kernel receipt scheduler.{key}")
        ):
            raise ValueError(f"Kernel reconciliation {key} differs from the receipt")
    finalizer_job = _require_dict(scheduler.get("finalizer_job"), "kernel reconciliation finalizer job")
    expected_finalizer = {
        "job_id": FINALIZER_JOB_ID,
        "job_name": FINALIZER_JOB_NAME,
        "state": "COMPLETED",
        "exit_code": "0:0",
        "qos": FINALIZER_QOS,
        "account": FINALIZER_ACCOUNT,
        "comment": "",
        "time_limit": "00:30:00",
        "time_limit_minutes": 30,
        "stdout_template": FINALIZER_STDIO_TEMPLATE,
        "stderr_template": FINALIZER_STDIO_TEMPLATE,
    }
    for key, value in expected_finalizer.items():
        if finalizer_job.get(key) != value:
            raise ValueError(f"Kernel reconciliation finalizer {key} differs")
    if set(finalizer_job) != {
        *kernel_execution.SCHEDULER_RECEIPT_FIELDS - {"submitted_batch_script_sha256"},
        "stdout_template",
        "stderr_template",
    }:
        raise ValueError("Kernel reconciliation finalizer has the wrong exact field inventory")
    if (
        isinstance(finalizer_job.get("elapsed_seconds"), bool)
        or not isinstance(finalizer_job.get("elapsed_seconds"), int)
        or finalizer_job["elapsed_seconds"] <= 0
    ):
        raise ValueError("Kernel reconciliation finalizer elapsed time is invalid")
    evidence = _require_dict(payload.get("finalizer_evidence"), "kernel reconciliation finalizer evidence")
    capture = _require_dict(evidence.get("submitted_script_capture"), "finalizer submitted script capture")
    if capture != _fixed_finalizer_script_capture(kernel_root, finalizer_job):
        raise ValueError("Kernel reconciliation submitted-script capture differs")
    if evidence.get("allocation_log") != _fixed_finalizer_log_evidence(validated["identity"], receipt):
        raise ValueError("Kernel reconciliation finalizer log evidence differs")
    if evidence.get("receipt_mtime") != _receipt_mtime_evidence(receipt_path, receipt, finalizer_job):
        raise ValueError("Kernel reconciliation receipt chronology differs")
    if payload.get("source_provenance") != _control_plane_source_provenance():
        raise ValueError("Kernel reconciliation source provenance differs")
    if payload.get("implementation") != file_identity(Path(__file__)):
        raise ValueError("Kernel reconciliation implementation identity differs")
    checks = _require_dict(payload.get("checks"), "kernel reconciliation checks")
    if set(checks) != KERNEL_RECONCILIATION_CHECK_FIELDS or any(value is not True for value in checks.values()):
        raise ValueError("Kernel reconciliation checks are not the exact all-true inventory")
    if raw != canonical_json_bytes(payload):
        raise RuntimeError("Kernel reconciliation changed during static replay")
    return {"reconciliation": payload, "identity": file_identity(resolved)}


def _validated_kernel(
    kernel_root: Path,
    kernel_validation_path: Path | None,
    kernel_reconciliation_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    kernel_root = kernel_root.expanduser().resolve()
    probe_dir = kernel_root / "probe"
    output_path = kernel_root / "kernel.json"
    source_state = source_provenance.verify_snapshot(
        kernel_root,
        verify_imports=False,
        require_launch=False,
    )
    snapshot = Path(str(source_state["snapshot_path"])).resolve()
    validator_path = snapshot / "user/tianhaowu/rsci/probe_known_cost_tag_kernel.py"
    _identity_matches(
        file_identity(Path(kernel_probe.__file__)),
        validator_path,
        "imported kernel-probe dependency",
    )
    _identity_matches(
        file_identity(Path(source_provenance.__file__)),
        snapshot / "user/tianhaowu/rsci/source_provenance.py",
        "imported source_provenance dependency",
    )
    validation_summary = _run_exact_validator(
        validator_path,
        [
            "validate-result",
            "--probe-dir",
            str(probe_dir),
            "--output",
            str(output_path),
        ],
    )
    _, result = _read_canonical_json(output_path)
    identity = file_identity(output_path)
    if validation_summary.get("command") != "validate-result":
        raise ValueError("Kernel validator did not execute its validate-result command")
    if validation_summary.get("output_sha256") != identity["sha256"]:
        raise ValueError("Kernel validator returned a different result SHA-256")
    if result.get("schema_version") != kernel_probe.SCHEMA_VERSION:
        raise ValueError("Kernel result schema differs from kernel-v2")
    if result.get("probe_id") != kernel_probe.PROBE_ID:
        raise ValueError("Kernel result is not the preregistered kernel-v2 probe")
    decision = _require_dict(result.get("decision"), "kernel result decision")
    if validation_summary.get("eligible_design") != decision.get("eligible_design"):
        raise ValueError("Kernel validator and result disagree on the eligible design")
    summary = _require_dict(result.get("kernel_summary"), "kernel result summary")
    if validation_summary.get("median_off_diagonal") != summary.get("median_off_diagonal"):
        raise ValueError("Kernel validator and result disagree on the analytic kernel median")
    if validation_summary.get("finite_step_ordering_passed") != decision.get("finite_step_ordering_passed"):
        raise ValueError("Kernel validator and result disagree on the finite-step ordering gate")
    if kernel_validation_path is None:
        adjacent_validation = kernel_root / "kernel_validation.json"
        if adjacent_validation.exists():
            kernel_validation_path = adjacent_validation
    if kernel_validation_path is None:
        raise FileNotFoundError("Kernel validation summary is required")
    execution_receipt = _validated_kernel_execution_receipt(
        kernel_root / kernel_execution.RECEIPT_NAME,
        verify_scheduler=False,
    )
    if kernel_reconciliation_path is None:
        kernel_reconciliation_path = kernel_root / KERNEL_RECONCILIATION_NAME
    reconciliation = validate_kernel_reconciliation(kernel_reconciliation_path)
    if reconciliation["reconciliation"]["receipt"] != execution_receipt["identity"]:
        raise ValueError("Kernel reconciliation and execution receipt identities differ")
    if execution_receipt["receipt"]["gpu_run_summary"]["eligible_design"] != decision.get("eligible_design"):
        raise ValueError("Kernel execution receipt and result disagree on the eligible design")
    source_manifest = file_identity(kernel_root / source_provenance.MANIFEST_NAME)
    source_record = _source_provenance_record(kernel_root, source_state)
    if source_record["manifest"] != source_manifest:
        raise RuntimeError("Kernel source provenance identity changed during validation")
    return result, {
        "result": identity,
        "independent_replay": {
            "validator": file_identity(validator_path),
            "result_sha256_replayed": True,
            "probe_artifacts_replayed": True,
            "recorded_result_internal_algebra_and_decision_replayed": True,
            "model_gradients_or_objectives_recomputed": False,
        },
        "execution_receipt": execution_receipt["identity"],
        "execution_receipt_validator": execution_receipt["validator"],
        "execution_receipt_validator_source": execution_receipt["validator_source_provenance"],
        "execution_receipt_validation_summary_sha256": execution_receipt["validation_summary_sha256"],
        "finalizer_reconciliation": reconciliation["identity"],
        "external_validation_artifact": _optional_kernel_validation(
            kernel_validation_path,
            identity,
            result,
        ),
        "source_provenance": {
            **source_record,
            "snapshot_path": source_state["snapshot_path"],
        },
    }


def _identity_matches(identity: dict[str, Any], path: Path, name: str) -> None:
    actual = file_identity(path)
    if identity.get("sha256") != actual["sha256"] or identity.get("size_bytes") != actual["size_bytes"]:
        raise ValueError(f"{name} differs from the launch source snapshot: {path}")


def _validate_snapshot_sources(
    snapshot: Path,
    preflight_report: dict[str, Any],
) -> None:
    implementations = _require_dict(
        preflight_report.get("implementation_identities"),
        "preflight implementation_identities",
    )
    if set(implementations) != set(IMPLEMENTATION_REPOSITORY_PATHS):
        raise ValueError("Preflight implementation inventory differs from the frozen contract")
    for name, relative in IMPLEMENTATION_REPOSITORY_PATHS.items():
        identity = _require_dict(implementations[name], f"preflight implementation {name}")
        _identity_matches(identity, snapshot / relative, f"preflight implementation {name}")


def _expected_composition_paths(
    preflight_report: dict[str, Any],
    arm_filename: str,
) -> tuple[Path, Path, Path]:
    inputs = _require_dict(preflight_report.get("inputs"), "preflight inputs")
    base = _repository_relative(Path(str(inputs.get("base_config_path"))))
    config_root = _repository_relative(Path(str(inputs.get("config_root"))))
    return base, config_root / "common.toml", config_root / arm_filename


def _validate_composition(
    *,
    snapshot: Path,
    launch_materialization: dict[str, Any],
    preflight_report: dict[str, Any],
    arm_filename: str,
    arm_report: dict[str, Any],
) -> list[dict[str, Any]]:
    relative_paths = _expected_composition_paths(preflight_report, arm_filename)
    expected_strings = [path.as_posix() for path in relative_paths]
    if launch_materialization.get("config_paths") != expected_strings:
        raise ValueError(f"{arm_filename} was not materialized from base, common, overlay in exact order")
    audit = _require_dict(preflight_report.get("config_audit"), "preflight config_audit")
    identities = (
        _require_dict(audit.get("base"), "preflight base identity"),
        _require_dict(audit.get("common"), "preflight common identity"),
        _require_dict(arm_report.get("overlay_identity"), f"{arm_filename} overlay identity"),
    )
    result = []
    for role, relative, expected in zip(("base", "common", "overlay"), relative_paths, identities, strict=True):
        path = snapshot / relative
        _identity_matches(expected, path, f"{arm_filename} {role} config")
        result.append({"role": role, "repository_path": relative.as_posix(), **file_identity(path)})
    return result


def _project_like(actual: object, expected: object, name: str) -> object:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError(f"{name} is not an object in the generated config")
        missing = sorted(set(expected) - set(actual))
        if missing:
            raise ValueError(f"{name} is missing generated keys {missing}")
        return {
            key: _project_like(actual[key], expected_value, f"{name}.{key}") for key, expected_value in expected.items()
        }
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError(f"{name} generated list length differs")
        return [
            _project_like(actual_value, expected_value, f"{name}[{index}]")
            for index, (actual_value, expected_value) in enumerate(zip(actual, expected, strict=True))
        ]
    return actual


def _expected_resolved_config(snapshot: Path, composition: list[dict[str, Any]]) -> dict[str, Any]:
    by_role = {str(item["role"]): item for item in composition}
    if set(by_role) != {"base", "common", "overlay"}:
        raise ValueError("Config composition does not contain base, common, and overlay exactly once")
    resolved: dict[str, Any] = {}
    for role in ("base", "common", "overlay"):
        relative = Path(str(by_role[role]["repository_path"]))
        resolved = preflight.deep_merge(resolved, _load_toml(snapshot / relative))
    return resolved


def _expected_scientific_projection(resolved: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "max_steps",
        "seq_len",
        "ckpt",
        "model",
        "tokenizer",
        "trainer",
        "inference",
        "orchestrator",
        "wandb",
        "weight_broadcast",
    )
    missing = [key for key in keys if key not in resolved]
    if missing:
        raise ValueError(f"Resolved scientific config is missing {missing}")
    return {key: copy.deepcopy(resolved[key]) for key in keys}


def _generated_scientific_projection(
    *,
    expected: dict[str, Any],
    trainer: dict[str, Any],
    orchestrator: dict[str, Any],
    inference: dict[str, Any],
) -> dict[str, Any]:
    model_names = {
        str(_require_dict(trainer.get("model"), "trainer.model").get("name")),
        str(
            _require_dict(
                _require_dict(orchestrator.get("student"), "orchestrator.student").get("model"),
                "orchestrator.student.model",
            ).get("name")
        ),
        str(_require_dict(inference.get("model"), "inference.model").get("name")),
    }
    if len(model_names) != 1:
        raise ValueError("Generated trainer, orchestrator, and inference model names differ")
    tokenizer = _require_dict(trainer.get("tokenizer"), "trainer.tokenizer")
    orchestrator_tokenizer = _require_dict(orchestrator.get("tokenizer"), "orchestrator.tokenizer")
    expected_tokenizer = _require_dict(expected.get("tokenizer"), "expected.tokenizer")
    if _project_like(orchestrator_tokenizer, expected_tokenizer, "orchestrator.tokenizer") != _project_like(
        tokenizer,
        expected_tokenizer,
        "trainer.tokenizer",
    ):
        raise ValueError("Generated trainer and orchestrator tokenizer projections differ")

    expected_ckpt = _require_dict(expected.get("ckpt"), "expected.ckpt")
    trainer_ckpt = _project_like(trainer.get("ckpt"), expected_ckpt, "trainer.ckpt")
    orchestrator_ckpt = _project_like(orchestrator.get("ckpt"), expected_ckpt, "orchestrator.ckpt")
    if trainer_ckpt != orchestrator_ckpt:
        raise ValueError("Generated trainer and orchestrator checkpoint projections differ")
    expected_wandb = _require_dict(expected.get("wandb"), "expected.wandb")
    trainer_wandb = _project_like(trainer.get("wandb"), expected_wandb, "trainer.wandb")
    orchestrator_wandb = _project_like(orchestrator.get("wandb"), expected_wandb, "orchestrator.wandb")
    if trainer_wandb != orchestrator_wandb:
        raise ValueError("Generated trainer and orchestrator W&B projections differ")
    expected_broadcast = _require_dict(expected.get("weight_broadcast"), "expected.weight_broadcast")
    trainer_broadcast = _project_like(
        trainer.get("weight_broadcast"),
        expected_broadcast,
        "trainer.weight_broadcast",
    )
    orchestrator_broadcast = _project_like(
        orchestrator.get("weight_broadcast"),
        expected_broadcast,
        "orchestrator.weight_broadcast",
    )
    if trainer_broadcast != orchestrator_broadcast:
        raise ValueError("Generated trainer and orchestrator weight-broadcast projections differ")
    inference_broadcast = _require_dict(inference.get("weight_broadcast"), "inference.weight_broadcast")
    if inference_broadcast.get("type") != expected_broadcast.get("type"):
        raise ValueError("Generated inference weight-broadcast type differs")

    generated_orchestrator = copy.deepcopy(orchestrator)
    generated_orchestrator["rollouts_per_example"] = orchestrator.get("group_size")
    generated_eval = _require_dict(generated_orchestrator.get("eval"), "orchestrator.eval")
    generated_eval["rollouts_per_example"] = generated_eval.get("group_size")
    actual = {
        "max_steps": trainer.get("max_steps"),
        "seq_len": orchestrator.get("seq_len"),
        "ckpt": trainer_ckpt,
        "model": {"name": model_names.pop()},
        "tokenizer": tokenizer,
        "trainer": trainer,
        "inference": inference,
        "orchestrator": generated_orchestrator,
        "wandb": trainer_wandb,
        "weight_broadcast": trainer_broadcast,
    }
    if orchestrator.get("max_steps") != actual["max_steps"]:
        raise ValueError("Generated trainer and orchestrator max_steps differ")
    if _require_dict(trainer.get("model"), "trainer.model").get("seq_len") != actual["seq_len"]:
        raise ValueError("Generated trainer and orchestrator sequence lengths differ")
    projected = _project_like(actual, expected, "generated scientific config")
    if canonical_json_bytes(projected) != canonical_json_bytes(expected):
        raise ValueError("Generated scientific config values differ from the expected projection")
    return projected


def _validate_scientific_projection(
    *,
    snapshot: Path,
    composition: list[dict[str, Any]],
    arm_report: dict[str, Any],
    trainer: dict[str, Any],
    orchestrator: dict[str, Any],
    inference: dict[str, Any],
) -> dict[str, Any]:
    resolved = _expected_resolved_config(snapshot, composition)
    resolved_sha256 = canonical_json_sha256(resolved)
    if resolved_sha256 != arm_report.get("resolved_config_sha256"):
        raise ValueError("Recomputed source composition differs from the preflight resolved config hash")
    expected = _expected_scientific_projection(resolved)
    generated = _generated_scientific_projection(
        expected=expected,
        trainer=trainer,
        orchestrator=orchestrator,
        inference=inference,
    )
    if canonical_json_bytes(generated) != canonical_json_bytes(expected):
        raise ValueError("Generated resolved scientific config differs from the preflight composition")
    parsed_bundle = {
        "trainer": trainer,
        "orchestrator": orchestrator,
        "inference": inference,
    }
    return {
        "source_composition_sha256": resolved_sha256,
        "projection_sha256": canonical_json_sha256(generated),
        "projection": generated,
        "parsed_resolved_bundle_sha256": canonical_json_sha256(parsed_bundle),
        "parsed_resolved_bundle_file_count": len(parsed_bundle),
    }


def _one_sbatch_directive(lines: list[str], name: str) -> str:
    prefix = f"#SBATCH --{name}="
    values = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    if len(values) != 1 or not values[0]:
        raise ValueError(f"SLURM script must declare exactly one --{name}")
    return values[0]


def _one_shell_export(lines: list[str], name: str) -> str:
    prefix = f"export {name}="
    values = [line.removeprefix(prefix).strip('"') for line in lines if line.startswith(prefix)]
    if len(values) != 1 or not values[0]:
        raise ValueError(f"SLURM script must declare exactly one export {name}")
    return values[0]


def _validate_launcher_projection(
    *,
    resolved: dict[str, Any],
    trainer: dict[str, Any],
    sbatch_path: Path,
) -> dict[str, Any]:
    expected_deployment = _require_dict(resolved.get("deployment"), "resolved.deployment")
    expected_slurm = _require_dict(resolved.get("slurm"), "resolved.slurm")
    expected_output = str(resolved.get("output_dir"))
    lines = sbatch_path.read_text(encoding="utf-8").splitlines()
    total_nodes = int(_one_sbatch_directive(lines, "nodes"))
    gpus_directive = _one_sbatch_directive(lines, "gres")
    if not gpus_directive.startswith("gpu:"):
        raise ValueError("SLURM script GRES is not an exact GPU count")
    actual_deployment = {
        "type": "multi_node",
        "num_train_nodes": int(_one_shell_export(lines, "NUM_TRAIN_NODES")),
        "num_infer_nodes": int(_one_shell_export(lines, "NODES_PER_INFER_REPLICA")),
        "num_infer_replicas": int(_one_shell_export(lines, "NUM_INFER_REPLICAS")),
        "gpus_per_node": int(_one_shell_export(lines, "GPUS_PER_NODE")),
    }
    expected_total_nodes = actual_deployment["num_train_nodes"] + (
        actual_deployment["num_infer_nodes"] * actual_deployment["num_infer_replicas"]
    )
    if total_nodes != expected_total_nodes:
        raise ValueError("SLURM total nodes differ from the generated deployment exports")
    if int(gpus_directive.removeprefix("gpu:")) != actual_deployment["gpus_per_node"]:
        raise ValueError("SLURM GPU directive differs from GPUS_PER_NODE")
    if canonical_json_bytes(actual_deployment) != canonical_json_bytes(expected_deployment):
        raise ValueError("Generated SLURM deployment differs from the preflight composition")

    pre_run = str(expected_slurm.get("pre_run_command"))
    actual_slurm = {
        "job_name": _one_sbatch_directive(lines, "job-name"),
        "partition": _one_sbatch_directive(lines, "partition"),
        "account": _one_sbatch_directive(lines, "account"),
        "time": _one_sbatch_directive(lines, "time"),
        "project_dir": _one_shell_export(lines, "PROJECT_DIR"),
        "pre_run_command": pre_run if pre_run in lines else None,
        "sync_environment": not any(line.strip() == "# Do not sync to avoid conflicts with lockfile" for line in lines),
    }
    expected_slurm_projection = {
        key: expected_slurm[key]
        for key in (
            "job_name",
            "partition",
            "account",
            "time",
            "project_dir",
            "pre_run_command",
            "sync_environment",
        )
    }
    if canonical_json_bytes(actual_slurm) != canonical_json_bytes(expected_slurm_projection):
        raise ValueError("Generated SLURM launcher fields differ from the preflight composition")
    actual_output = _one_shell_export(lines, "OUTPUT_DIR")
    if actual_output != expected_output or str(trainer.get("output_dir")) != expected_output:
        raise ValueError("Generated trainer/SLURM output directory differs from the preflight composition")
    projection = {
        "deployment": actual_deployment,
        "slurm": actual_slurm,
        "output_dir": actual_output,
        "rl.sbatch": file_identity(sbatch_path),
    }
    return {
        "projection": projection,
        "projection_sha256": canonical_json_sha256(projection),
    }


def _known_cost_train_input(
    launch_inputs: dict[str, Any],
    arm_report: dict[str, Any],
    preflight_report: dict[str, Any],
    tokenizer_path: Path,
) -> dict[str, Any]:
    datasets = launch_inputs.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("Sealed launch inputs have no dataset inventory")
    train_inputs = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise ValueError("Sealed launch input dataset is not an object")
        environments = dataset.get("environments")
        if isinstance(environments, list) and any(
            isinstance(environment, dict) and environment.get("phase") == "train" for environment in environments
        ):
            train_inputs.append(dataset)
    if len(train_inputs) != 1:
        raise ValueError("A known-cost arm must bind exactly one training dataset")
    train = train_inputs[0]
    seed = arm_report.get("block_seed")
    bank_audit = _require_dict(preflight_report.get("bank_audit"), "preflight bank_audit")
    bank = _require_dict(bank_audit.get(str(seed)), f"preflight bank_audit[{seed}]")
    expected_output = _require_dict(bank.get("output"), f"preflight bank {seed} output")
    expected_manifest = _require_dict(bank.get("manifest"), f"preflight bank {seed} manifest")
    if Path(str(train.get("resolved_path"))).resolve() != Path(str(expected_output.get("path"))).resolve():
        raise ValueError("Sealed training dataset path differs from the preflight bank")
    if train.get("sha256") != expected_output.get("sha256"):
        raise ValueError("Sealed training dataset hash differs from the preflight bank")
    if train.get("size_bytes") != expected_output.get("size_bytes"):
        raise ValueError("Sealed training dataset size differs from the preflight bank")

    adjacent = _require_dict(train.get("adjacent_manifest"), "known-cost adjacent dataset manifest")
    if adjacent.get("artifact_type") != "rsci_known_cost_neutral_tag_bank":
        raise ValueError("Known-cost training input has the wrong adjacent-manifest artifact type")
    if Path(str(adjacent.get("resolved_path"))).resolve() != Path(str(expected_manifest.get("path"))).resolve():
        raise ValueError("Sealed adjacent manifest path differs from the preflight bank manifest")
    if adjacent.get("sha256") != expected_manifest.get("sha256"):
        raise ValueError("Sealed adjacent manifest hash differs from the preflight bank manifest")
    if adjacent.get("declared_dataset_sha256") != train.get("sha256"):
        raise ValueError("Adjacent manifest does not declare the sealed training dataset hash")
    if adjacent.get("declared_dataset_size_bytes") != train.get("size_bytes"):
        raise ValueError("Adjacent manifest does not declare the sealed training dataset size")
    tag_tokenization = _require_dict(adjacent.get("tag_tokenization"), "adjacent tag tokenization")
    if tag_tokenization.get("equal_token_counts") is not True:
        raise ValueError("Adjacent manifest does not seal equal known-cost tag token counts")
    if tag_tokenization.get("common_token_count") != 13:
        raise ValueError("Known-cost tag prefixes do not have the frozen 13-token length")
    if Path(str(tag_tokenization.get("configured_tokenizer_path"))).resolve() != tokenizer_path.resolve():
        raise ValueError("Adjacent manifest tokenizer path differs from the explicit tokenizer")
    tokenizer = _require_dict(launch_inputs.get("tokenizer"), "sealed tokenizer identity")
    if tag_tokenization.get("configured_tokenizer_sha256") != tokenizer.get("sha256"):
        raise ValueError("Adjacent manifest tokenizer identity differs from the sealed launch tokenizer")
    return train


def _sbatch_job_name(path: Path) -> str:
    values = [
        line.removeprefix("#SBATCH --job-name=")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("#SBATCH --job-name=")
    ]
    if len(values) != 1 or not values[0]:
        raise ValueError(f"SLURM script must declare exactly one nonempty job name: {path}")
    return values[0]


def _validate_run(
    *,
    arm_filename: str,
    arm_report: dict[str, Any],
    preflight_report: dict[str, Any],
    tokenizer_path: Path,
) -> dict[str, Any]:
    run_dir = Path(str(arm_report.get("output_dir"))).expanduser().resolve()
    source_state = source_provenance.verify_snapshot(
        run_dir,
        verify_imports=False,
        require_launch=True,
    )
    snapshot = Path(str(source_state.get("snapshot_path"))).resolve()
    _validate_snapshot_sources(snapshot, preflight_report)
    launch_materialization = _require_dict(
        source_state.get("launch_materialization"),
        f"{arm_filename} launch materialization",
    )
    composition = _validate_composition(
        snapshot=snapshot,
        launch_materialization=launch_materialization,
        preflight_report=preflight_report,
        arm_filename=arm_filename,
        arm_report=arm_report,
    )
    launch_inputs = _require_dict(source_state.get("launch_inputs"), f"{arm_filename} launch inputs")
    train_input = _known_cost_train_input(
        launch_inputs,
        arm_report,
        preflight_report,
        tokenizer_path,
    )

    trainer_path = run_dir / "configs" / "trainer.toml"
    orchestrator_path = run_dir / "configs" / "orchestrator.toml"
    inference_path = run_dir / "configs" / "inference.toml"
    trainer = _load_toml(trainer_path)
    orchestrator = _load_toml(orchestrator_path)
    inference = _load_toml(inference_path)
    scientific_projection = _validate_scientific_projection(
        snapshot=snapshot,
        composition=composition,
        arm_report=arm_report,
        trainer=trainer,
        orchestrator=orchestrator,
        inference=inference,
    )
    expected_wandb = arm_report.get("wandb_name")
    if Path(str(trainer.get("output_dir"))).resolve() != run_dir:
        raise ValueError(f"{arm_filename} trainer output directory differs from its frozen arm")
    for source_name, resolved in (("trainer", trainer), ("orchestrator", orchestrator)):
        wandb = _require_dict(resolved.get("wandb"), f"{arm_filename} {source_name}.wandb")
        if wandb.get("name") != expected_wandb:
            raise ValueError(f"{arm_filename} {source_name} W&B name differs from its frozen arm")

    sbatch_path = run_dir / "rl.sbatch"
    launcher_projection = _validate_launcher_projection(
        resolved=_expected_resolved_config(snapshot, composition),
        trainer=trainer,
        sbatch_path=sbatch_path,
    )
    job_name = _sbatch_job_name(sbatch_path)
    if job_name != arm_report.get("job_name"):
        raise ValueError(f"{arm_filename} SLURM job name differs from its frozen arm")
    if Path(str(arm_report.get("project_dir"))).resolve() != snapshot:
        raise ValueError(f"{arm_filename} project_dir differs from its source snapshot")
    launch_artifacts = _require_dict(
        source_state.get("launch_artifacts_sha256"),
        f"{arm_filename} launch artifacts",
    )
    sbatch_identity = file_identity(sbatch_path)
    if launch_artifacts.get("rl.sbatch") != sbatch_identity["sha256"]:
        raise ValueError(f"{arm_filename} sealed SLURM hash differs from rl.sbatch")
    source_record = _source_provenance_record(run_dir, source_state)

    return {
        "arm_filename": arm_filename,
        "block_seed": arm_report.get("block_seed"),
        "condition": arm_report.get("condition"),
        "family": arm_report.get("family"),
        "nominal_p": arm_report.get("nominal_p"),
        "output_dir": str(run_dir),
        "project_dir": str(snapshot),
        "job_name": job_name,
        "wandb_name": expected_wandb,
        "resolved_config_sha256": arm_report.get("resolved_config_sha256"),
        "config_composition": composition,
        "scientific_config_projection": scientific_projection,
        "launcher_config_projection": launcher_projection,
        "resolved_configs": {
            "inference": file_identity(inference_path),
            "orchestrator": file_identity(orchestrator_path),
            "trainer": file_identity(trainer_path),
        },
        "sbatch": sbatch_identity,
        "source_provenance": {
            **source_record,
            "launch_materialization": launch_materialization,
            "launch_artifacts_sha256": launch_artifacts,
            "launch_inputs": launch_inputs,
        },
        "known_cost_training_input": train_input,
    }


def _validate_unique_run_identities(runs: list[dict[str, Any]]) -> dict[str, list[str]]:
    fields = {
        "output_dir": [str(run["output_dir"]) for run in runs],
        "project_dir": [str(run["project_dir"]) for run in runs],
        "job_name": [str(run["job_name"]) for run in runs],
        "wandb_name": [str(run["wandb_name"]) for run in runs],
        "sbatch_path": [str(_require_dict(run["sbatch"], "run.sbatch")["path"]) for run in runs],
        "sbatch_sha256": [str(_require_dict(run["sbatch"], "run.sbatch")["sha256"]) for run in runs],
    }
    for name, values in fields.items():
        if len(values) != len(set(values)):
            raise ValueError(f"Eligible arms repeat {name}")
    return {name: sorted(values) for name, values in fields.items()}


def _validate_common_launch_source(runs: list[dict[str, Any]]) -> dict[str, str]:
    commits = {
        str(_require_dict(run["source_provenance"], "run.source_provenance")["parent_commit_sha"]) for run in runs
    }
    trees = {
        str(_require_dict(run["source_provenance"], "run.source_provenance")["source_tree_sha256"]) for run in runs
    }
    runtime_identities = {
        str(_require_dict(run["source_provenance"], "run.source_provenance")["runtime_identity_sha256"]) for run in runs
    }
    if len(commits) != 1 or len(trees) != 1 or len(runtime_identities) != 1:
        raise ValueError("Eligible arms do not share one commit-pinned source and environment identity")
    commit = commits.pop()
    tree = trees.pop()
    runtime_identity = runtime_identities.pop()
    _require_sha256(tree, "launch source tree")
    _require_sha256(runtime_identity, "launch runtime identity")
    if re.fullmatch(r"[0-9a-f]{40,64}", commit) is None:
        raise ValueError("Launch parent commit is not a Git object id")
    return {
        "parent_commit_sha": commit,
        "source_tree_sha256": tree,
        "runtime_identity_sha256": runtime_identity,
    }


def _build_arm_inventory(
    *,
    arm_reports: dict[str, Any],
    eligible_filenames: tuple[str, ...],
    design: str,
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    eligible_set = set(eligible_filenames)
    run_by_filename = {str(run["arm_filename"]): run for run in runs}
    if set(run_by_filename) != eligible_set:
        raise ValueError("Validated run records do not equal the preregistered eligible arm set")
    inventory = []
    for filename in _expected_arm_inventory():
        arm = _require_dict(arm_reports.get(filename), f"preflight arm {filename}")
        is_eligible = filename in eligible_set
        item: dict[str, Any] = {
            "arm_filename": filename,
            "block_seed": arm.get("block_seed"),
            "condition": arm.get("condition"),
            "expected_output_dir": arm.get("output_dir"),
            "overlay_identity": arm.get("overlay_identity"),
            "resolved_config_sha256": arm.get("resolved_config_sha256"),
            "decision_status": "eligible" if is_eligible else "excluded",
            "decision_reason": (
                f"selected_by_{design}" if is_eligible else f"excluded_by_preregistered_{design}_decision"
            ),
        }
        if is_eligible:
            run = run_by_filename[filename]
            item["sealed_source_provenance"] = run["source_provenance"]["manifest"]
            item["sbatch"] = run["sbatch"]
        inventory.append(item)
    if len(inventory) != 30 or sum(item["decision_status"] == "eligible" for item in inventory) != len(
        eligible_filenames
    ):
        raise RuntimeError("Preregistered arm inventory does not partition all 30 arms exactly")
    return inventory


def build_intent(
    *,
    run_root: Path,
    preflight_report_path: Path,
    kernel_root: Path,
    tokenizer_path: Path,
    kernel_validation_path: Path | None = None,
    kernel_reconciliation_path: Path | None = None,
) -> dict[str, Any]:
    run_root = run_root.expanduser().resolve()
    tokenizer_path = tokenizer_path.expanduser().resolve()
    preflight_report, preflight_record = _validated_preflight(preflight_report_path, tokenizer_path)
    kernel_result, kernel_record = _validated_kernel(
        kernel_root,
        kernel_validation_path,
        kernel_reconciliation_path,
    )
    design, eligible_filenames = eligible_arm_filenames(kernel_result)

    config_audit = _require_dict(preflight_report.get("config_audit"), "preflight config_audit")
    arm_reports = _require_dict(config_audit.get("arms"), "preflight config_audit.arms")
    runs = []
    for arm_filename in eligible_filenames:
        arm_report = _require_dict(arm_reports.get(arm_filename), f"preflight arm {arm_filename}")
        expected_dir = Path(str(arm_report.get("output_dir"))).resolve()
        if expected_dir != run_root / f"block-{arm_report.get('block_seed')}" / expected_dir.name:
            raise ValueError(f"{arm_filename} output directory is outside the exact study run root")
        runs.append(
            _validate_run(
                arm_filename=arm_filename,
                arm_report=arm_report,
                preflight_report=preflight_report,
                tokenizer_path=tokenizer_path,
            )
        )

    unique_identities = _validate_unique_run_identities(runs)
    launch_source = _validate_common_launch_source(runs)
    control_plane_source = _control_plane_source_provenance()
    preflight_source = _require_dict(
        preflight_record.get("source_provenance"),
        "preflight source provenance",
    )
    kernel_source = _require_dict(kernel_record.get("source_provenance"), "kernel source provenance")
    for name, source in (("preflight", preflight_source), ("kernel", kernel_source)):
        if source.get("parent_commit_sha") != launch_source["parent_commit_sha"]:
            raise ValueError(f"{name} source commit differs from the eligible RL runs")
        if source.get("source_tree_sha256") != launch_source["source_tree_sha256"]:
            raise ValueError(f"{name} source tree differs from the eligible RL runs")
        if source.get("runtime_identity_sha256") != launch_source["runtime_identity_sha256"]:
            raise ValueError(f"{name} environment identity differs from the eligible RL runs")
    kernel_model = _require_dict(kernel_result.get("model"), "kernel model identity")
    first_launch_inputs = _require_dict(
        _require_dict(runs[0]["source_provenance"], "run source provenance").get("launch_inputs"),
        "run launch inputs",
    )
    launch_tokenizer = _require_dict(first_launch_inputs.get("tokenizer"), "run tokenizer identity")
    if Path(str(kernel_model.get("configured_name"))).resolve() != tokenizer_path:
        raise ValueError("Kernel model path differs from the explicit launch tokenizer/model")
    if Path(str(launch_tokenizer.get("resolved_path"))).resolve() != tokenizer_path:
        raise ValueError("Sealed launch tokenizer path differs from the explicit tokenizer")

    arm_inventory = _build_arm_inventory(
        arm_reports=arm_reports,
        eligible_filenames=eligible_filenames,
        design=design,
        runs=runs,
    )

    dispatch_payload = {
        "schema_version": 1,
        "study_id": STUDY_ID,
        "eligible_design": design,
        "max_live_arms": MAX_ARMS_PER_DISPATCH,
        "required_qos": REQUIRED_DISPATCH_QOS,
        "required_state_root": str(REQUIRED_DISPATCH_STATE_ROOT),
        "scheduler_override_transport": "explicit_sbatch_cli_v1",
        "eligible_arms": [
            {
                "arm_filename": run["arm_filename"],
                "output_dir": run["output_dir"],
                "job_name": run["job_name"],
                "wandb_name": run["wandb_name"],
                "sbatch": run["sbatch"],
                "source_provenance": run["source_provenance"]["manifest"],
                "scientific_config_projection_sha256": run["scientific_config_projection"]["projection_sha256"],
                "parsed_resolved_bundle_sha256": run["scientific_config_projection"]["parsed_resolved_bundle_sha256"],
                "launcher_config_projection_sha256": run["launcher_config_projection"]["projection_sha256"],
            }
            for run in runs
        ],
    }

    intent: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "inputs": {
            "run_root": str(run_root),
            "preflight_report": str(preflight_report_path.expanduser().resolve()),
            "kernel_root": str(kernel_root.expanduser().resolve()),
            "kernel_validation": (
                str(Path(kernel_record["external_validation_artifact"]["identity"]["path"]).resolve())
                if kernel_record["external_validation_artifact"] is not None
                else None
            ),
            "kernel_reconciliation": kernel_record["finalizer_reconciliation"]["path"],
            "tokenizer_path": str(tokenizer_path),
        },
        "launch_source": launch_source,
        "control_plane_source": control_plane_source,
        "production_preflight": preflight_record,
        "kernel": kernel_record,
        "preregistered_decision": {
            "rule": kernel_result["decision"]["rule"],
            "eligible_design": design,
            "eligible_arm_count": len(eligible_filenames),
            "eligible_arm_filenames": list(eligible_filenames),
            "kernel_summary": kernel_result["kernel_summary"],
            "kernel_decision": kernel_result["decision"],
        },
        "arm_inventory": arm_inventory,
        "eligible_runs": runs,
        "unique_runtime_identities": unique_identities,
        "protected_dispatch_plan": {
            "status": "content_addressed_inventory_only_not_scheduler_authorization",
            "payload": dispatch_payload,
            "payload_sha256": canonical_json_sha256(dispatch_payload),
            "future_dispatcher_requirements": {
                "exact_allowlist_only": True,
                "intent_and_dispatch_payload_hash_required": True,
                "per_arm_write_once_intent_and_receipt_required": True,
                "scheduler_reconciliation_required_after_ambiguous_submission": True,
            },
        },
        "dispatch_policy": {
            "submission_supported_by_this_tool": False,
            "actual_submission_requires_a_separate_explicit_command": True,
            "this_intent_is_not_scheduler_authorization": True,
            "manual_sbatch_is_not_authorized": True,
            "required_control_tmux": CONTROL_TMUX,
            "max_arms_per_dispatch": MAX_ARMS_PER_DISPATCH,
            "max_live_arms": MAX_ARMS_PER_DISPATCH,
            "required_qos": REQUIRED_DISPATCH_QOS,
            "required_state_root": str(REQUIRED_DISPATCH_STATE_ROOT),
            "required_scheduler_cli_overrides": {
                "account": "sealed_sbatch_account",
                "comment": "content_addressed_per_arm",
                "qos": REQUIRED_DISPATCH_QOS,
            },
            "required_environment_unsets": ["SBATCH_OUTPUT", "SBATCH_ERROR"],
        },
        "implementation": file_identity(Path(__file__)),
        "implementation_dependencies": {
            "kernel_execution_finalizer": kernel_record["execution_receipt_validator"],
            "known_cost_preflight": file_identity(Path(preflight.__file__)),
            "kernel_probe": file_identity(Path(kernel_probe.__file__)),
            "source_provenance": file_identity(Path(source_provenance.__file__)),
        },
        "checks": {
            "control_plane_is_commit_environment_and_runtime_pinned": True,
            "production_preflight_exact_file_and_self_hash_replayed": True,
            "kernel_v2_internal_algebra_and_preregistered_decision_replayed": True,
            "kernel_v2_execution_receipt_historical_finalizer_replayed": True,
            "kernel_finalizer_reconciliation_statically_replayed": True,
            "kernel_scheduler_and_finalizer_live_evidence_frozen_before_intent": True,
            "eligible_config_compositions_match_the_frozen_inventory": True,
            "all_30_arms_partitioned_into_eligible_and_excluded_sets": True,
            "every_run_is_commit_pinned_materialized_and_sealed": True,
            "every_run_binds_the_known_cost_adjacent_data_sidecar": True,
            "output_slurm_wandb_and_sbatch_identities_are_unique": True,
            "this_tool_performed_no_submission": True,
        },
    }
    intent["payload_without_self_hash_sha256"] = canonical_json_sha256(intent)
    return intent


def write_intent_atomic(path: Path, intent: dict[str, Any]) -> dict[str, Any]:
    path = path.expanduser().resolve()
    inputs = _require_dict(intent.get("inputs"), "intent inputs")
    expected_path = Path(str(inputs.get("run_root"))).expanduser().resolve() / INTENT_NAME
    if path != expected_path:
        raise ValueError(f"Submission intent must be adjacent to its run root at {expected_path}")
    content = canonical_json_bytes(intent)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different immutable submission intent: {path}")
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


def validate_intent(path: Path, *, tokenizer_path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if stat.S_IMODE(path.stat().st_mode) & 0o222:
        raise ValueError("Submission intent is writable")
    raw, intent = _read_canonical_json(path)
    if intent.get("schema_version") != SCHEMA_VERSION or intent.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Submission intent has the wrong schema or artifact type")
    self_hash = _require_sha256(
        intent.get("payload_without_self_hash_sha256"),
        "intent payload_without_self_hash_sha256",
    )
    payload = dict(intent)
    payload.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(payload) != self_hash:
        raise ValueError("Submission intent self hash differs from its canonical payload")
    inputs = _require_dict(intent.get("inputs"), "intent inputs")
    expected_path = Path(str(inputs.get("run_root"))).expanduser().resolve() / INTENT_NAME
    if path != expected_path:
        raise ValueError(f"Submission intent is not adjacent to its recorded run root: {expected_path}")
    recorded_tokenizer = Path(str(inputs.get("tokenizer_path"))).resolve()
    if tokenizer_path.expanduser().resolve() != recorded_tokenizer:
        raise ValueError("Explicit validation tokenizer differs from the submission intent")
    expected = build_intent(
        run_root=Path(str(inputs.get("run_root"))),
        preflight_report_path=Path(str(inputs.get("preflight_report"))),
        kernel_root=Path(str(inputs.get("kernel_root"))),
        tokenizer_path=recorded_tokenizer,
        kernel_validation_path=(
            Path(str(inputs["kernel_validation"])) if inputs.get("kernel_validation") is not None else None
        ),
        kernel_reconciliation_path=Path(str(inputs.get("kernel_reconciliation"))),
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Submission intent differs from an independent replay of all launch inputs")
    return {"intent": intent, "identity": file_identity(path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile = subparsers.add_parser("materialize-reconciliation")
    reconcile.add_argument("--kernel-root", type=Path, required=True)
    validate_reconciliation = subparsers.add_parser("validate-reconciliation")
    validate_reconciliation.add_argument("--reconciliation", type=Path, required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--run-root", type=Path, required=True)
    materialize.add_argument("--preflight-report", type=Path, required=True)
    materialize.add_argument("--kernel-root", type=Path, required=True)
    materialize.add_argument("--kernel-validation", type=Path)
    materialize.add_argument("--kernel-reconciliation", type=Path)
    materialize.add_argument("--tokenizer", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--intent", type=Path, required=True)
    validate.add_argument("--tokenizer", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize-reconciliation":
        payload = _build_kernel_reconciliation(args.kernel_root)
        identity = write_kernel_reconciliation_once(
            args.kernel_root / KERNEL_RECONCILIATION_NAME,
            payload,
        )
        validated = validate_kernel_reconciliation(identity["path"])
        if validated["identity"] != identity:
            raise RuntimeError("Kernel reconciliation changed during materialization")
        summary = {
            "command": args.command,
            "reconciliation": identity,
            "submission_performed": False,
        }
    elif args.command == "validate-reconciliation":
        validated = validate_kernel_reconciliation(args.reconciliation)
        summary = {
            "command": args.command,
            "reconciliation": validated["identity"],
            "submission_performed": False,
        }
    elif args.command == "materialize":
        intent = build_intent(
            run_root=args.run_root,
            preflight_report_path=args.preflight_report,
            kernel_root=args.kernel_root,
            tokenizer_path=args.tokenizer,
            kernel_validation_path=args.kernel_validation,
            kernel_reconciliation_path=args.kernel_reconciliation,
        )
        identity = write_intent_atomic(args.run_root / INTENT_NAME, intent)
        summary = {
            "command": "materialize",
            "intent": identity,
            "eligible_design": intent["preregistered_decision"]["eligible_design"],
            "eligible_arm_count": intent["preregistered_decision"]["eligible_arm_count"],
            "submission_performed": False,
        }
    else:
        validated = validate_intent(args.intent, tokenizer_path=args.tokenizer)
        summary = {
            "command": "validate",
            "intent": validated["identity"],
            "eligible_design": validated["intent"]["preregistered_decision"]["eligible_design"],
            "eligible_arm_count": validated["intent"]["preregistered_decision"]["eligible_arm_count"],
            "submission_performed": False,
        }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
