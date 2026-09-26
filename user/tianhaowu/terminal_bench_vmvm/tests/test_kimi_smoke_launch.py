from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import kimi_smoke_launch as launch
import pytest

X2P_VALUES = {
    "X2P_ENV": "synthetic-x2p-environment",
    "X2P_CFG_ENV": "synthetic-x2p-configuration",
    "X2P_PROXY_URL": "http://synthetic.invalid/v1",
}


def _environment(tmp_path: Path) -> dict[str, str]:
    project = tmp_path / "project"
    wrapper = project / "user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_gate.sbatch"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/bin/bash\n")
    spec = tmp_path / "spec.yaml"
    readiness = tmp_path / "readiness.json"
    certificate = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    for path in (spec, readiness, certificate, key):
        path.write_text("fixture\n")
    return {
        "PROJECT_DIR": str(project.resolve()),
        "EVAL_EXPECTED_PRIME_RL_REVISION": "1" * 40,
        "EVAL_DEPLOYMENT_ID": "deployment-test",
        "INFERENCE_DEPLOYMENT_SPEC": str(spec.resolve()),
        "INFERENCE_DEPLOYMENT_SPEC_SHA256": "2" * 64,
        "INFERENCE_READINESS_CHECKPOINT": str(readiness.resolve()),
        "SMOKE_OUTPUT_DIR": str((tmp_path / "fresh-smoke").resolve()),
        "THRIFT_TLS_CL_CERT_PATH": str(certificate.resolve()),
        "THRIFT_TLS_CL_KEY_PATH": str(key.resolve()),
        **X2P_VALUES,
    }


def _git_runner(argv, **_kwargs):
    operation = argv[3]
    if operation == "rev-parse":
        return subprocess.CompletedProcess(argv, 0, "1" * 40 + "\n", "")
    if operation == "status":
        return subprocess.CompletedProcess(argv, 0, "", "")
    if operation == "symbolic-ref":
        return subprocess.CompletedProcess(argv, 1, "", "")
    raise AssertionError(f"unexpected git operation: {operation}")


def test_submit_uses_anonymous_descriptor_and_closes_it(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["UNRELATED_SECRET"] = "must-not-cross-boundary"
    observed: dict[str, object] = {}

    def runner(argv, **kwargs):
        descriptor = kwargs["pass_fds"][0]
        observed["descriptor"] = descriptor
        status = os.fstat(descriptor)
        observed["mode"] = stat.S_IMODE(status.st_mode)
        observed["nlink"] = status.st_nlink
        observed["argv"] = argv
        observed["environment"] = kwargs["env"]
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os,sys; os.write(1, os.read(int(sys.argv[1]), 1048576))",
                str(descriptor),
            ],
            check=False,
            capture_output=True,
            pass_fds=(descriptor,),
            env={},
        )
        observed["child_returncode"] = child.returncode
        observed["export"] = dict(record.decode().split("=", 1) for record in child.stdout.rstrip(b"\0").split(b"\0"))
        return subprocess.CompletedProcess(argv, 0, "12345\n", "")

    receipt = launch.submit_smoke(
        environment,
        command_runner=runner,
        validation_runner=_git_runner,
    )

    descriptor = observed["descriptor"]
    assert isinstance(descriptor, int)
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert observed["mode"] == 0o600
    assert observed["nlink"] == 0
    assert observed["child_returncode"] == 0
    assert observed["environment"] == {}
    argv = observed["argv"]
    assert isinstance(argv, list)
    assert f"--time={launch.EXPECTED_SLURM_TIME_LIMIT}" in argv
    assert f"--export-file={descriptor}" in argv
    assert all(secret not in repr(argv) for secret in X2P_VALUES.values())
    exported = observed["export"]
    assert isinstance(exported, dict)
    assert {key: exported[key] for key in launch.REQUIRED_X2P_ENV} == X2P_VALUES
    assert "UNRELATED_SECRET" not in exported
    assert exported["KIMI_TB4_STOP_AFTER_SMOKE"] == "1"
    assert receipt["launch_contract"] == launch.validate_launch_contract(
        {
            "schema_version": 2,
            "transport": launch.EXPECTED_TRANSPORT,
            "slurm_time_limit": launch.EXPECTED_SLURM_TIME_LIMIT,
            "x2p_environment_sha256": {
                key: hashlib.sha256(value.encode()).hexdigest() for key, value in X2P_VALUES.items()
            },
        }
    )
    persisted = b"".join(path.read_bytes() for path in Path(environment["PROJECT_DIR"]).rglob("*") if path.is_file())
    assert all(secret.encode() not in persisted for secret in X2P_VALUES.values())
    assert all(secret not in repr(receipt) for secret in X2P_VALUES.values())


@pytest.mark.parametrize("missing", [*launch.REQUIRED_X2P_ENV, "THRIFT_TLS_CL_CERT_PATH"])
def test_submit_rejects_missing_tuple_or_auth_before_sbatch(tmp_path: Path, missing: str) -> None:
    environment = _environment(tmp_path)
    secret_values = tuple(X2P_VALUES.values())
    environment.pop(missing)

    with pytest.raises(launch.KimiSmokeLaunchError) as caught:
        launch.submit_smoke(
            environment,
            command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not submit")),
        )

    assert all(secret not in str(caught.value) for secret in secret_values)


def test_validate_current_job_requires_exact_commitments_and_scheduler_time(tmp_path: Path) -> None:
    environment, contract = launch._submission_environment(_environment(tmp_path))
    environment["SLURM_JOB_ID"] = "12345"
    calls: list[list[str]] = []
    scheduler_environments: list[dict[str, str]] = []

    def scheduler(argv, **kwargs):
        calls.append(argv)
        scheduler_environments.append(kwargs["env"])
        return subprocess.CompletedProcess(
            argv,
            0,
            f"12345|{launch.EXPECTED_SLURM_TIME_LIMIT}\n",
            "",
        )

    assert launch.validate_current_job_environment(environment, scheduler_runner=scheduler) == contract
    assert calls == [[launch.DEFAULT_SQUEUE, "--noheader", "--jobs=12345", "--format=%A|%l"]]
    assert scheduler_environments == [{}]

    for key, replacement, error in (
        ("KIMI_SMOKE_X2P_PROXY_URL_SHA256", "0" * 64, "launch_environment_commitment_mismatch"),
        ("X2P_PROXY_URL", "rotated-secret", "launch_environment_commitment_mismatch"),
    ):
        changed = {**environment, key: replacement}
        with pytest.raises(launch.KimiSmokeLaunchError, match=error):
            launch.validate_current_job_environment(changed, scheduler_runner=scheduler)

    def drifted(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "12345|2-00:00:00\n", "")

    with pytest.raises(launch.KimiSmokeLaunchError, match="scheduler_time_limit_mismatch"):
        launch.validate_current_job_environment(environment, scheduler_runner=drifted)


def test_existing_output_and_resume_are_rejected_before_sbatch(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    Path(environment["SMOKE_OUTPUT_DIR"]).mkdir()
    with pytest.raises(launch.KimiSmokeLaunchError, match="smoke_output_not_fresh"):
        launch.submit_smoke(environment)

    environment = _environment(tmp_path / "other")
    environment["RESUME_DIR"] = "/forbidden"
    with pytest.raises(launch.KimiSmokeLaunchError, match="resume_forbidden"):
        launch.submit_smoke(environment)


def test_sbatch_failure_does_not_expose_x2p_values(tmp_path: Path) -> None:
    environment = _environment(tmp_path)

    def rejected(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 1, "", " ".join(X2P_VALUES.values()))

    with pytest.raises(launch.KimiSmokeLaunchError) as caught:
        launch.submit_smoke(
            environment,
            command_runner=rejected,
            validation_runner=_git_runner,
        )

    assert str(caught.value) == "sbatch_submission_failed"
    assert all(secret not in str(caught.value) for secret in X2P_VALUES.values())


def test_submit_requires_exact_clean_detached_source(tmp_path: Path) -> None:
    environment = _environment(tmp_path)

    def attached(argv, **_kwargs):
        operation = argv[3]
        if operation == "rev-parse":
            return subprocess.CompletedProcess(argv, 0, "1" * 40 + "\n", "")
        if operation == "status":
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 0, "refs/heads/unsafe\n", "")

    with pytest.raises(launch.KimiSmokeLaunchError, match="project_source_not_detached"):
        launch.submit_smoke(
            environment,
            command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not submit")),
            validation_runner=attached,
        )
