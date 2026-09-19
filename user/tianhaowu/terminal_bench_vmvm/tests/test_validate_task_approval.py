from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from snapshot_eval_inputs import snapshot
from validate_task_approval import TaskApprovalError, main, validate_approval


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_source_config(path: Path, task_file: Path, digest: str, count: int) -> None:
    path.write_text(
        f"num_tasks = {count}\n"
        "[taskset]\n"
        'id = "terminal-bench-vmvm"\n'
        f'task_file = "{task_file}"\n'
        f'task_file_sha256 = "{digest}"\n'
    )


def _approved_run(tmp_path: Path) -> tuple[Path, Path, str]:
    approved = tmp_path / "approved.txt"
    approved.write_bytes(b"opaque-001\nopaque-002\n")
    digest = _sha256(approved.read_bytes())
    source_config = tmp_path / "source.toml"
    _write_source_config(source_config, approved, digest, 2)
    run_dir = tmp_path / "run"
    snapshot(source_config, run_dir / "inputs")
    return run_dir, approved, digest


def test_fresh_snapshot_matches_external_approval(tmp_path: Path) -> None:
    run_dir, approved, digest = _approved_run(tmp_path)

    validate_approval(run_dir / "inputs", approved, digest)


@pytest.mark.parametrize(
    ("task_bytes", "count", "error"),
    [
        (b"opaque-001\nopaque-001\n", 2, "external_approval_duplicates"),
        (b"opaque-001\nopaque-002\n", 1, "source_config_task_count_mismatch"),
    ],
)
def test_rejects_duplicates_and_count_mismatches(
    tmp_path: Path,
    task_bytes: bytes,
    count: int,
    error: str,
) -> None:
    approved = tmp_path / "approved.txt"
    approved.write_bytes(task_bytes)
    digest = _sha256(task_bytes)
    config = tmp_path / "source.toml"
    _write_source_config(config, approved, digest, count)
    inputs = tmp_path / "inputs"
    snapshot(config, inputs)

    with pytest.raises(TaskApprovalError, match=f"^{error}$"):
        validate_approval(inputs, approved, digest)


def test_rejects_inline_tasks_even_when_task_file_is_approved(tmp_path: Path) -> None:
    run_dir, approved, digest = _approved_run(tmp_path)
    source_config = run_dir / "inputs" / "source_config.toml"
    source_config.write_text(source_config.read_text() + 'tasks = ["opaque-001"]\n')
    manifest_path = run_dir / "inputs" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["config"]["sha256"] = _sha256(source_config.read_bytes())
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(TaskApprovalError, match="^source_config_inline_tasks_forbidden$"):
        validate_approval(run_dir / "inputs", approved, digest)


def test_rejects_snapshot_tampering(tmp_path: Path) -> None:
    run_dir, approved, digest = _approved_run(tmp_path)
    (run_dir / "inputs" / "task_file.txt").write_bytes(b"opaque-003\n")

    with pytest.raises(TaskApprovalError, match="^task_snapshot_hash_mismatch$"):
        validate_approval(run_dir / "inputs", approved, digest)


def test_resume_config_must_reuse_approved_snapshot(tmp_path: Path) -> None:
    run_dir, approved, digest = _approved_run(tmp_path)
    saved_config = run_dir / "config.toml"
    _write_source_config(saved_config, run_dir / "inputs" / "task_file.txt", digest, 2)

    validate_approval(
        run_dir / "inputs",
        approved,
        digest,
        resume_config=saved_config,
    )

    alternate = tmp_path / "alternate.txt"
    alternate.write_bytes(approved.read_bytes())
    _write_source_config(saved_config, alternate, digest, 2)
    with pytest.raises(TaskApprovalError, match="^resume_config_task_file_mismatch$"):
        validate_approval(
            run_dir / "inputs",
            approved,
            digest,
            resume_config=saved_config,
        )


def test_requires_lowercase_digest_and_emits_fixed_error(tmp_path: Path, capsys) -> None:
    run_dir, approved, digest = _approved_run(tmp_path)

    status = main(
        [
            "--inputs-dir",
            str(run_dir / "inputs"),
            "--approved-task-file",
            str(approved),
            "--approved-task-file-sha256",
            digest.upper(),
        ]
    )

    assert status == 2
    assert capsys.readouterr().err == "task_approval_error:external_approval_hash_invalid\n"


def test_success_emits_only_safe_approval_metadata(tmp_path: Path, capsys) -> None:
    run_dir, approved, digest = _approved_run(tmp_path)

    status = main(
        [
            "--inputs-dir",
            str(run_dir / "inputs"),
            "--approved-task-file",
            str(approved),
            "--approved-task-file-sha256",
            digest,
        ]
    )

    assert status == 0
    captured = capsys.readouterr()
    assert captured.out == f"{digest}\t2\n"
    assert captured.err == ""


def test_generic_launcher_rejects_task_overrides_and_keeps_dry_run() -> None:
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"
    text = wrapper.read_text()

    assert "The eval launcher accepts no overrides except a single --dry-run" in text
    assert 'args+=("$@")' not in text
    assert "--dry-run" in text
    assert "EVAL_APPROVED_TASK_FILE" in text
    assert "EVAL_APPROVED_TASK_FILE_SHA256" in text
    assert "EVAL_CONFIG_SHA256" in text
    assert "DIRECT_QWEN_APPROVED_TASK_FILE" in text
    assert "DIRECT_QWEN_APPROVED_TASK_FILE_SHA256" in text
    assert "validate_task_approval.py" in text
    assert "run_direct_qwen_eval_driver.sh" in text
    assert "eval_run_identity.py" in text
    assert "inference_route_guard.py" in text
    assert "--approved-task-file-sha256" in text
    assert "--approved-task-count" in text
    assert "eval_run_identity_sha256" in text
    assert "eval_run_identity.json" in (Path(__file__).parents[1] / "eval_run_identity.py").read_text()
    assert 'python3 "$workflow_dir/mobius_launch_certificate.py" verify' in text
    assert '--certificate-sha256 "$promotion_certificate_sha256"' in text
    assert '--production-config "$eval_config"' in text
    assert '--approved-manifest "$approved_task_file"' in text
    assert '--approved-manifest-sha256 "$approved_task_file_sha256"' in text
    assert '--deployment-id "$eval_deployment_id"' in text
    assert '--deployment-spec "$deployment_spec"' in text
    assert '--deployment-spec-sha256 "$deployment_spec_sha256"' in text
    assert '--readiness-checkpoint "$readiness_checkpoint"' in text
    assert '--readiness-checkpoint-sha256 "$readiness_checkpoint_sha256"' in text
    assert '--deployment-proxy-info "$inference_proxy_info"' in text
    assert '--deployment-proxy-info-sha256 "$inference_proxy_info_sha256"' in text
    assert '--capacity-smoke-checkpoint "$smoke_checkpoint"' in text
    assert '--capacity-smoke-checkpoint-sha256 "$smoke_checkpoint_sha256"' in text
    assert '--requested-lease-start-concurrency "$effective_lease_start_concurrency"' in text
    assert "without EVAL_MODEL override" in text
    assert "deployment-local INFERENCE_PROXY_INFO endpoint" in text
    assert "--routing-deployment-id" in text
    assert "INFERENCE_DEPLOYMENT_ID routing must match EVAL_DEPLOYMENT_ID metadata" in text
    assert "EVAL_PROMOTION_CERTIFICATE" in text
    assert "EVAL_EXPECTED_PRIME_RL_REVISION" in text
    assert "PROJECT_DIR revision does not match EVAL_EXPECTED_PRIME_RL_REVISION" in text
    assert text.index('python3 "$workflow_dir/mobius_launch_certificate.py" verify') < text.index(
        'python3 "$workflow_dir/eval_run_identity.py"'
    )
    assert text.index('python3 "$workflow_dir/mobius_launch_certificate.py" verify') < text.index(
        'mkdir -p "$output_dir"'
    )
    assert text.index('python3 "$workflow_dir/eval_run_identity.py"') < text.index(
        'python3 "$workflow_dir/inference_route_guard.py"'
    )
    assert text.index("Guarded Kimi evaluations cannot resume") < text.index(
        'python3 "$workflow_dir/eval_run_identity.py"'
    )
    assert text.index('python3 "$workflow_dir/inference_route_guard.py"') < text.index(
        'from verifiers.v1.cli.eval.main import main; main()\' "${args[@]}"',
        text.index('python3 "$workflow_dir/eval_run_identity.py"'),
    )
    guard = text[text.index('python3 "$workflow_dir/inference_route_guard.py"') :]
    for argument in (
        '--deployment-id "$eval_deployment_id"',
        '--deployment-spec "$deployment_spec"',
        '--deployment-spec-sha256 "$deployment_spec_sha256"',
        '--readiness-checkpoint "$readiness_checkpoint"',
        '--readiness-checkpoint-sha256 "$readiness_checkpoint_sha256"',
        '--proxy-info "$inference_proxy_info"',
        '--proxy-info-sha256 "$inference_proxy_info_sha256"',
        '--expected-model "$eval_expected_model"',
        '--eval-run-identity "$output_dir/eval_run_identity.json"',
        '--eval-run-identity-sha256 "$eval_run_identity_sha256"',
        '--eval-invocations "$output_dir/eval_invocations.jsonl"',
        '--results "$output_dir/results.jsonl"',
        '--success-receipt "$output_dir/route_guard_success.json"',
    ):
        assert argument in guard


def _launcher_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path]:
    project_dir = Path(__file__).resolve().parents[4]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv_log = tmp_path / "uv.args"
    python_log = tmp_path / "python.called"

    fake_uv = fake_bin / "uv"
    fake_uv.write_text('#!/bin/bash\nprintf "%s\\0" "$@" > "$FAKE_UV_LOG"\n')
    fake_uv.chmod(0o755)
    fake_python = fake_bin / "python3"
    fake_python.write_text('#!/bin/bash\nprintf called > "$FAKE_PYTHON_LOG"\nexit 97\n')
    fake_python.chmod(0o755)
    fake_uname = fake_bin / "uname"
    fake_uname.write_text('#!/bin/bash\nprintf "x86_64\\n"\n')
    fake_uname.chmod(0o755)

    x86_site = tmp_path / "x86_site"
    (x86_site / "pydantic").mkdir(parents=True)
    config = tmp_path / "eval.toml"
    config.write_text('[taskset]\nid = "terminal-bench-vmvm"\n')
    output_dir = tmp_path / "output"

    env = os.environ.copy()
    for name in (
        "DIRECT_QWEN_APPROVED_TASK_FILE",
        "DIRECT_QWEN_APPROVED_TASK_FILE_SHA256",
        "EVAL_APPROVED_TASK_FILE",
        "EVAL_APPROVED_TASK_FILE_SHA256",
        "EVAL_CONFIG_SHA256",
        "EVAL_MODEL",
        "INFERENCE_BASE_URL",
        "INFERENCE_DEPLOYMENT_ID",
        "INFERENCE_JOB_ID",
        "INFERENCE_PROXY_INFO",
        "INFERENCE_PROXY_INFO_SHA256",
        "INFERENCE_PROXY_URL",
        "RESUME_DIR",
        "EVAL_RUN_ROLE",
        "EVAL_DEPLOYMENT_ID",
        "EVAL_EXPECTED_MODEL",
        "EVAL_EXPECTED_PRIME_RL_REVISION",
        "EVAL_DATASET_REVISION",
        "EVAL_DATASET_ARCHIVE",
        "EVAL_DATASET_ARCHIVE_SHA256",
        "EVAL_DATASET_CONTENT_SHA256",
        "INFERENCE_DEPLOYMENT_SPEC",
        "INFERENCE_DEPLOYMENT_SPEC_SHA256",
        "INFERENCE_READINESS_CHECKPOINT",
        "INFERENCE_READINESS_CHECKPOINT_SHA256",
        "INFERENCE_SMOKE_CHECKPOINT",
        "INFERENCE_SMOKE_CHECKPOINT_SHA256",
        "EVAL_PROMOTION_CERTIFICATE",
        "EVAL_PROMOTION_CERTIFICATE_SHA256",
    ):
        env.pop(name, None)
    env.update(
        {
            "EVAL_CONFIG": str(config),
            "FAKE_PYTHON_LOG": str(python_log),
            "FAKE_UV_LOG": str(uv_log),
            "OUTPUT_DIR": str(output_dir),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PROJECT_DIR": str(project_dir),
            "PYTHON_BIN_X86_64": str(fake_python),
            "PYTHON_SITE_X86_64": str(x86_site),
            "SLURM_JOB_ID": "12345",
            "UV_BIN_X86_64": str(fake_uv),
        }
    )
    return env, output_dir, uv_log, python_log


def test_launcher_dry_run_skips_approval_endpoint_lock_and_snapshot(tmp_path: Path) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper), "--dry-run"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    args = uv_log.read_bytes().split(b"\0")[:-1]
    assert b"--dry-run" in args
    assert args[args.index(b"@") + 1] == env["EVAL_CONFIG"].encode()
    assert args[args.index(b"--output-dir") + 1] == str(output_dir).encode()
    assert b"--client.base-url" not in args
    assert b"validate_task_approval.py" not in args
    assert not python_log.exists()
    assert not (output_dir / ".writer.lock").exists()
    assert not (output_dir / "inputs").exists()


def test_launcher_rejects_wrong_config_hash_before_mutation(tmp_path: Path) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    env["EVAL_CONFIG_SHA256"] = "a" * 64
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper), "--dry-run"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "EVAL_CONFIG does not match EVAL_CONFIG_SHA256\n"
    assert not uv_log.exists()
    assert not python_log.exists()
    assert not output_dir.exists()


def test_real_launcher_fails_before_endpoint_or_snapshot_without_approval(tmp_path: Path) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "An external approved task file and lowercase SHA-256 are required\n"
    assert not uv_log.exists()
    assert not python_log.exists()
    assert not output_dir.exists()


def test_guarded_launcher_rejects_partial_output_resume_before_mutation(
    tmp_path: Path,
) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    failed_run = tmp_path / "failed-generation-a"
    failed_run.mkdir()
    results = failed_run / "results.jsonl"
    invocations = failed_run / "eval_invocations.jsonl"
    results.write_text('{"partial":"row"}\n')
    invocations.write_text('{"generation":"A","resume":false}\n')
    before = {path: path.read_bytes() for path in (results, invocations)}
    env.update(
        {
            "EVAL_RUN_ROLE": "smoke",
            "OUTPUT_DIR": str(output_dir),
            "RESUME_DIR": str(failed_run),
        }
    )
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "Guarded Kimi evaluations cannot resume; use a fresh OUTPUT_DIR\n"
    assert {path: path.read_bytes() for path in before} == before
    assert not output_dir.exists()
    assert not uv_log.exists()
    assert not python_log.exists()


def test_real_launcher_requires_readiness_bound_proxy_hash_before_mutation(tmp_path: Path) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    env.update(
        {
            "EVAL_APPROVED_TASK_FILE": "/opaque/approved",
            "EVAL_APPROVED_TASK_FILE_SHA256": "a" * 64,
            "EVAL_DATASET_REVISION": "b" * 40,
            "EVAL_DEPLOYMENT_ID": "deployment-test",
            "EVAL_EXPECTED_MODEL": "Kimi-K3",
            "EVAL_RUN_ROLE": "smoke",
            "INFERENCE_DEPLOYMENT_SPEC": "/opaque/spec.yaml",
            "INFERENCE_DEPLOYMENT_SPEC_SHA256": "d" * 64,
            "INFERENCE_PROXY_INFO": "/opaque/proxy_info.json",
            "INFERENCE_READINESS_CHECKPOINT": "/opaque/readiness.json",
            "INFERENCE_READINESS_CHECKPOINT_SHA256": "e" * 64,
        }
    )
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "INFERENCE_PROXY_INFO and INFERENCE_PROXY_INFO_SHA256 are required\n"
    assert not uv_log.exists()
    assert not python_log.exists()
    assert not output_dir.exists()


def test_guarded_launcher_rejects_wrong_pinned_project_revision_before_mutation(
    tmp_path: Path,
) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    fake_git = Path(env["PATH"].split(":", 1)[0]) / "git"
    fake_git.write_text(
        "#!/bin/bash\n"
        'if [[ "$*" == *rev-parse* ]]; then\n'
        "  printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'\n"
        "fi\n"
    )
    fake_git.chmod(0o755)
    env.update(
        {
            "EVAL_APPROVED_TASK_FILE": "/opaque/approved",
            "EVAL_APPROVED_TASK_FILE_SHA256": "a" * 64,
            "EVAL_DATASET_REVISION": "b" * 40,
            "EVAL_DEPLOYMENT_ID": "deployment-test",
            "EVAL_EXPECTED_MODEL": "Kimi-K3",
            "EVAL_EXPECTED_PRIME_RL_REVISION": "b" * 40,
            "EVAL_RUN_ROLE": "tb4",
            "INFERENCE_DEPLOYMENT_SPEC": "/opaque/spec.yaml",
            "INFERENCE_DEPLOYMENT_SPEC_SHA256": "d" * 64,
            "INFERENCE_PROXY_INFO": "/opaque/proxy_info.json",
            "INFERENCE_PROXY_INFO_SHA256": "1" * 64,
            "INFERENCE_READINESS_CHECKPOINT": "/opaque/readiness.json",
            "INFERENCE_READINESS_CHECKPOINT_SHA256": "e" * 64,
            "INFERENCE_SMOKE_CHECKPOINT": "/opaque/smoke.json",
            "INFERENCE_SMOKE_CHECKPOINT_SHA256": "f" * 64,
        }
    )
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == ("PROJECT_DIR revision does not match EVAL_EXPECTED_PRIME_RL_REVISION\n")
    assert not uv_log.exists()
    assert not python_log.exists()
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("override", "expected_error"),
    [
        (
            {"EVAL_MODEL": "not-approved"},
            "Mobius evaluation requires the certificate-bound Kimi-K3 model without EVAL_MODEL override\n",
        ),
        (
            {"INFERENCE_BASE_URL": "http://not-approved.invalid/v1"},
            "Evaluation requires only the readiness-bound deployment-local INFERENCE_PROXY_INFO endpoint\n",
        ),
    ],
)
def test_mobius_launcher_rejects_model_and_endpoint_overrides_before_mutation(
    tmp_path: Path,
    override: dict[str, str],
    expected_error: str,
) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    env.update(
        {
            "EVAL_APPROVED_TASK_FILE": "/opaque/approved",
            "EVAL_APPROVED_TASK_FILE_SHA256": "a" * 64,
            "EVAL_DATASET_REVISION": "b" * 40,
            "EVAL_DEPLOYMENT_ID": "deployment-test",
            "EVAL_EXPECTED_MODEL": "Kimi-K3",
            "EVAL_PROMOTION_CERTIFICATE": "/opaque/certificate",
            "EVAL_PROMOTION_CERTIFICATE_SHA256": "c" * 64,
            "EVAL_RUN_ROLE": "mobius",
            "INFERENCE_DEPLOYMENT_SPEC": "/opaque/spec.yaml",
            "INFERENCE_DEPLOYMENT_SPEC_SHA256": "d" * 64,
            "INFERENCE_PROXY_INFO": "/opaque/proxy_info.json",
            "INFERENCE_PROXY_INFO_SHA256": "1" * 64,
            "INFERENCE_READINESS_CHECKPOINT": "/opaque/readiness.json",
            "INFERENCE_READINESS_CHECKPOINT_SHA256": "e" * 64,
            "INFERENCE_SMOKE_CHECKPOINT": "/opaque/smoke.json",
            "INFERENCE_SMOKE_CHECKPOINT_SHA256": "f" * 64,
        }
    )
    env.update(override)
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == expected_error
    assert not uv_log.exists()
    assert not python_log.exists()
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("approval_env", "expected_error"),
    [
        (
            {"EVAL_APPROVED_TASK_FILE": "/opaque/approval"},
            "The EVAL task approval pair is incomplete\n",
        ),
        (
            {"DIRECT_QWEN_APPROVED_TASK_FILE_SHA256": "a" * 64},
            "The DIRECT_QWEN task approval pair is incomplete\n",
        ),
        (
            {
                "EVAL_APPROVED_TASK_FILE": "/opaque/eval",
                "EVAL_APPROVED_TASK_FILE_SHA256": "a" * 64,
                "DIRECT_QWEN_APPROVED_TASK_FILE": "/opaque/direct",
                "DIRECT_QWEN_APPROVED_TASK_FILE_SHA256": "b" * 64,
            },
            "The task approval environment pairs conflict\n",
        ),
    ],
)
def test_launcher_rejects_partial_or_conflicting_approval_pairs(
    tmp_path: Path,
    approval_env: dict[str, str],
    expected_error: str,
) -> None:
    env, output_dir, uv_log, python_log = _launcher_environment(tmp_path)
    env.update(approval_env)
    wrapper = Path(__file__).parents[1] / "run_eval.sbatch"

    result = subprocess.run(
        ["bash", str(wrapper)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == expected_error
    assert not uv_log.exists()
    assert not python_log.exists()
    assert not output_dir.exists()
