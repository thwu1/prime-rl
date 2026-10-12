#!/usr/bin/env python3
"""Submit and verify the credential-safe Kimi two-task smoke launch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
EXPECTED_SLURM_TIME_LIMIT = "3-00:00:00"
EXPECTED_TRANSPORT = "anonymous_slurm_export_fd_v1"
DEFAULT_SBATCH = "/usr/bin/sbatch"
DEFAULT_SQUEUE = "/usr/bin/squeue"
DEFAULT_GIT = "/usr/bin/git"
SUBMISSION_TIMEOUT_SECONDS = 30.0
SCHEDULER_TIMEOUT_SECONDS = 30.0
MAX_SCHEDULER_OUTPUT_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
METADATA_ID_RE = re.compile(r"[A-Za-z0-9._:-]+")
SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
REQUIRED_X2P_ENV = ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL")
X2P_COMMITMENT_ENV = {
    "X2P_ENV": "KIMI_SMOKE_X2P_ENV_SHA256",
    "X2P_CFG_ENV": "KIMI_SMOKE_X2P_CFG_ENV_SHA256",
    "X2P_PROXY_URL": "KIMI_SMOKE_X2P_PROXY_URL_SHA256",
}
LAUNCH_SCHEMA_ENV = "KIMI_SMOKE_LAUNCH_CONTRACT_SCHEMA_VERSION"
LAUNCH_TRANSPORT_ENV = "KIMI_SMOKE_LAUNCH_TRANSPORT"
LAUNCH_TIME_LIMIT_ENV = "KIMI_SMOKE_SLURM_TIME_LIMIT"
REQUIRED_GATE_ENV = (
    "PROJECT_DIR",
    "EVAL_EXPECTED_PRIME_RL_REVISION",
    "EVAL_DEPLOYMENT_ID",
    "INFERENCE_DEPLOYMENT_SPEC",
    "INFERENCE_DEPLOYMENT_SPEC_SHA256",
    "INFERENCE_READINESS_CHECKPOINT",
    "SMOKE_OUTPUT_DIR",
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
)
OPTIONAL_GATE_ENV = (
    "EVAL_DATASET_ARCHIVE",
    "EVAL_DATASET_ARCHIVE_SHA256",
    "EVAL_DATASET_CONTENT_SHA256",
    "PYTHON_SITE_X86_64",
    "UV_BIN_X86_64",
    "PYTHON_BIN_X86_64",
)
DATASET_ARCHIVE_ENV = (
    "EVAL_DATASET_ARCHIVE",
    "EVAL_DATASET_ARCHIVE_SHA256",
    "EVAL_DATASET_CONTENT_SHA256",
)


class KimiSmokeLaunchError(ValueError):
    """The smoke launch cannot satisfy its credential-safe contract."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _safe_value(value: object) -> bool:
    return isinstance(value, str) and bool(value) and not any(character in value for character in "\x00\r\n")


def x2p_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Return the complete raw tuple while keeping values out of failures."""

    if {key for key in REQUIRED_X2P_ENV if key in environment} != set(REQUIRED_X2P_ENV):
        raise KimiSmokeLaunchError("x2p_environment_invalid")
    values: dict[str, str] = {}
    for key in REQUIRED_X2P_ENV:
        value = environment.get(key)
        if not _safe_value(value):
            raise KimiSmokeLaunchError("x2p_environment_invalid")
        assert isinstance(value, str)
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise KimiSmokeLaunchError("x2p_environment_invalid") from error
        values[key] = value
    return values


def x2p_environment_sha256(environment: Mapping[str, str]) -> dict[str, str]:
    values = x2p_environment(environment)
    return {key: hashlib.sha256(values[key].encode()).hexdigest() for key in REQUIRED_X2P_ENV}


def validate_launch_contract(value: object) -> dict[str, Any]:
    """Validate the exact credential-free Kimi smoke launch contract."""

    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "transport",
            "slurm_time_limit",
            "x2p_environment_sha256",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("transport") != EXPECTED_TRANSPORT
        or value.get("slurm_time_limit") != EXPECTED_SLURM_TIME_LIMIT
    ):
        raise KimiSmokeLaunchError("launch_contract_invalid")
    commitments = value.get("x2p_environment_sha256")
    if (
        not isinstance(commitments, dict)
        or set(commitments) != set(REQUIRED_X2P_ENV)
        or any(
            not isinstance(commitments[key], str) or SHA256_RE.fullmatch(commitments[key]) is None
            for key in REQUIRED_X2P_ENV
        )
    ):
        raise KimiSmokeLaunchError("launch_contract_invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "transport": EXPECTED_TRANSPORT,
        "slurm_time_limit": EXPECTED_SLURM_TIME_LIMIT,
        "x2p_environment_sha256": {key: commitments[key] for key in REQUIRED_X2P_ENV},
    }


def launch_contract_from_environment(
    environment: Mapping[str, str],
    *,
    require_commitments: bool,
) -> dict[str, Any]:
    commitments = x2p_environment_sha256(environment)
    if require_commitments:
        if (
            environment.get(LAUNCH_SCHEMA_ENV) != str(SCHEMA_VERSION)
            or environment.get(LAUNCH_TRANSPORT_ENV) != EXPECTED_TRANSPORT
            or environment.get(LAUNCH_TIME_LIMIT_ENV) != EXPECTED_SLURM_TIME_LIMIT
            or any(environment.get(X2P_COMMITMENT_ENV[key]) != commitments[key] for key in REQUIRED_X2P_ENV)
        ):
            raise KimiSmokeLaunchError("launch_environment_commitment_mismatch")
    return validate_launch_contract(
        {
            "schema_version": SCHEMA_VERSION,
            "transport": EXPECTED_TRANSPORT,
            "slurm_time_limit": EXPECTED_SLURM_TIME_LIMIT,
            "x2p_environment_sha256": commitments,
        }
    )


def _encode_environment(values: Mapping[str, str]) -> bytes:
    records: list[bytes] = []
    for key in sorted(values):
        value = values[key]
        if not _safe_value(key) or not _safe_value(value) or "=" in key:
            raise KimiSmokeLaunchError("submission_environment_invalid")
        try:
            records.append(f"{key}={value}".encode("utf-8") + b"\x00")
        except UnicodeEncodeError as error:
            raise KimiSmokeLaunchError("submission_environment_invalid") from error
    return b"".join(records)


def _required_environment(environment: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in REQUIRED_GATE_ENV:
        value = environment.get(key)
        if not _safe_value(value):
            raise KimiSmokeLaunchError("gate_environment_invalid")
        assert isinstance(value, str)
        values[key] = value
    for key in OPTIONAL_GATE_ENV:
        value = environment.get(key)
        if value is not None:
            if not _safe_value(value):
                raise KimiSmokeLaunchError("gate_environment_invalid")
            values[key] = value
    dataset_present = {key for key in DATASET_ARCHIVE_ENV if key in values}
    if dataset_present not in (set(), set(DATASET_ARCHIVE_ENV)):
        raise KimiSmokeLaunchError("dataset_environment_invalid")
    if environment.get("RESUME_DIR"):
        raise KimiSmokeLaunchError("resume_forbidden")
    if environment.get("KIMI_TB4_STOP_AFTER_SMOKE") not in (None, "1") or environment.get("TB4_OUTPUT_DIR"):
        raise KimiSmokeLaunchError("smoke_only_launcher_invalid")
    if REVISION_RE.fullmatch(values["EVAL_EXPECTED_PRIME_RL_REVISION"]) is None:
        raise KimiSmokeLaunchError("project_revision_invalid")
    if METADATA_ID_RE.fullmatch(values["EVAL_DEPLOYMENT_ID"]) is None:
        raise KimiSmokeLaunchError("deployment_id_invalid")
    for key in ("INFERENCE_DEPLOYMENT_SPEC_SHA256", *DATASET_ARCHIVE_ENV[1:]):
        if key in values and SHA256_RE.fullmatch(values[key]) is None:
            raise KimiSmokeLaunchError("gate_environment_invalid")
    for key in (
        "PROJECT_DIR",
        "INFERENCE_DEPLOYMENT_SPEC",
        "INFERENCE_READINESS_CHECKPOINT",
        "THRIFT_TLS_CL_CERT_PATH",
        "THRIFT_TLS_CL_KEY_PATH",
    ):
        path = Path(values[key])
        try:
            status = path.stat()
        except OSError as error:
            raise KimiSmokeLaunchError("gate_path_invalid") from error
        if not path.is_absolute() or (not stat.S_ISREG(status.st_mode) and key != "PROJECT_DIR"):
            raise KimiSmokeLaunchError("gate_path_invalid")
        if key == "PROJECT_DIR" and not stat.S_ISDIR(status.st_mode):
            raise KimiSmokeLaunchError("gate_path_invalid")
    output = Path(values["SMOKE_OUTPUT_DIR"])
    if not output.is_absolute() or os.path.lexists(output):
        raise KimiSmokeLaunchError("smoke_output_not_fresh")
    return values


def _submission_environment(environment: Mapping[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
    values = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        **_required_environment(environment),
        "KIMI_TB4_STOP_AFTER_SMOKE": "1",
        LAUNCH_SCHEMA_ENV: str(SCHEMA_VERSION),
        LAUNCH_TRANSPORT_ENV: EXPECTED_TRANSPORT,
        LAUNCH_TIME_LIMIT_ENV: EXPECTED_SLURM_TIME_LIMIT,
    }
    raw_x2p = x2p_environment(environment)
    contract = launch_contract_from_environment(raw_x2p, require_commitments=False)
    for key, commitment_key in X2P_COMMITMENT_ENV.items():
        values[commitment_key] = contract["x2p_environment_sha256"][key]
    values.update(raw_x2p)
    return values, contract


def _parse_job_id(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode != 0:
        raise KimiSmokeLaunchError("sbatch_submission_failed")
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise KimiSmokeLaunchError("sbatch_response_invalid")
    job_id = lines[0].split(";", 1)[0]
    if SLURM_JOB_ID_RE.fullmatch(job_id) is None:
        raise KimiSmokeLaunchError("sbatch_response_invalid")
    return job_id


def _validate_project(
    project: Path,
    expected_revision: str,
    *,
    runner: CommandRunner,
) -> None:
    commands = (
        ([DEFAULT_GIT, "-C", str(project), "rev-parse", "--verify", "HEAD"], expected_revision),
        ([DEFAULT_GIT, "-C", str(project), "status", "--porcelain=v1", "--untracked-files=all"], ""),
    )
    for command, expected_output in commands:
        try:
            result = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=SCHEDULER_TIMEOUT_SECONDS,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise KimiSmokeLaunchError("project_source_unverifiable") from error
        if result.returncode != 0 or result.stdout.strip() != expected_output:
            raise KimiSmokeLaunchError("project_source_invalid")
    try:
        symbolic = runner(
            [DEFAULT_GIT, "-C", str(project), "symbolic-ref", "-q", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=SCHEDULER_TIMEOUT_SECONDS,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise KimiSmokeLaunchError("project_source_unverifiable") from error
    if symbolic.returncode != 1 or symbolic.stdout:
        raise KimiSmokeLaunchError("project_source_not_detached")


def submit_smoke(
    environment: Mapping[str, str],
    *,
    command_runner: CommandRunner = subprocess.run,
    validation_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    values, contract = _submission_environment(environment)
    configured_project = Path(values["PROJECT_DIR"])
    project = configured_project.resolve(strict=True)
    if configured_project != project or configured_project.is_symlink():
        raise KimiSmokeLaunchError("gate_path_invalid")
    output = Path(values["SMOKE_OUTPUT_DIR"]).resolve(strict=False)
    try:
        output.relative_to(project)
    except ValueError:
        pass
    else:
        raise KimiSmokeLaunchError("smoke_output_inside_project")
    wrapper = project / "user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_gate.sbatch"
    try:
        if wrapper.resolve(strict=True) != wrapper or not wrapper.is_file():
            raise KimiSmokeLaunchError("gate_wrapper_invalid")
    except (OSError, RuntimeError) as error:
        raise KimiSmokeLaunchError("gate_wrapper_invalid") from error
    _validate_project(
        project,
        values["EVAL_EXPECTED_PRIME_RL_REVISION"],
        runner=validation_runner,
    )
    encoded = _encode_environment(values)
    token = secrets.token_hex(8)
    try:
        with tempfile.TemporaryFile(mode="w+b") as export_file:
            descriptor = export_file.fileno()
            os.fchmod(descriptor, 0o600)
            status = os.fstat(descriptor)
            if (
                descriptor < 3
                or not stat.S_ISREG(status.st_mode)
                or stat.S_IMODE(status.st_mode) != 0o600
                or status.st_nlink != 0
            ):
                raise KimiSmokeLaunchError("transient_environment_invalid")
            export_file.write(encoded)
            export_file.flush()
            export_file.seek(0)
            result = command_runner(
                [
                    DEFAULT_SBATCH,
                    "--parsable",
                    f"--time={EXPECTED_SLURM_TIME_LIMIT}",
                    f"--job-name=k3-tb4-smoke-{token}",
                    f"--export-file={descriptor}",
                    str(wrapper),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=project,
                env={},
                pass_fds=(descriptor,),
                timeout=SUBMISSION_TIMEOUT_SECONDS,
            )
    except KimiSmokeLaunchError:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise KimiSmokeLaunchError("sbatch_submission_unknown") from error
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "submitted",
        "slurm_job_id": _parse_job_id(result),
        "launch_contract": contract,
    }


def validate_current_job_environment(
    environment: Mapping[str, str],
    *,
    scheduler_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    contract = launch_contract_from_environment(environment, require_commitments=True)
    job_id = environment.get("SLURM_JOB_ID")
    if not isinstance(job_id, str) or SLURM_JOB_ID_RE.fullmatch(job_id) is None:
        raise KimiSmokeLaunchError("slurm_job_id_invalid")
    try:
        result = scheduler_runner(
            [DEFAULT_SQUEUE, "--noheader", f"--jobs={job_id}", "--format=%A|%l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=SCHEDULER_TIMEOUT_SECONDS,
            env={},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise KimiSmokeLaunchError("scheduler_query_unavailable") from error
    if result.returncode != 0 or len(result.stdout) > MAX_SCHEDULER_OUTPUT_BYTES:
        raise KimiSmokeLaunchError("scheduler_query_unavailable")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or lines[0].split("|") != [job_id, EXPECTED_SLURM_TIME_LIMIT]:
        raise KimiSmokeLaunchError("scheduler_time_limit_mismatch")
    return contract


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("submit", "validate-current"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = submit_smoke(os.environ) if args.action == "submit" else validate_current_job_environment(os.environ)
    except (KimiSmokeLaunchError, OSError, RuntimeError, ValueError) as error:
        print(f"kimi_smoke_launch_error:{error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
