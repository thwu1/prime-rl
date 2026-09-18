from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import tarfile
from pathlib import Path

import launch_tb4_shard_wave as launcher
import pytest
from deployment_endpoint import load_deployment_endpoint
from launch_tb4_shard_wave import EXPECTED_VMVM_ENV, WaveLaunchError, launch_wave
from tb4_shard_workflow import canonical_json, create_plan


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_write(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


def _record(path: Path, **extra: object) -> dict[str, object]:
    return {"path": str(path.resolve()), "sha256": _sha256(path), **extra}


def _make_plan(tmp_path: Path, dataset: Path) -> tuple[Path, str]:
    identifiers = [hashlib.sha256(f"synthetic-case-{index}".encode()).hexdigest() for index in range(66)]
    universe = tmp_path / "private-universe.txt"
    _private_write(
        universe,
        "".join(f"{identifier}\n" for identifier in identifiers).encode(),
    )
    universe_sha256 = _sha256(universe)
    base = tmp_path / "base.toml"
    base.write_text(
        f'''model = "Kimi-K3"
num_tasks = 66
num_rollouts = 1
max_concurrent = 4
multiplex = 4
max_input_tokens = 262144
max_output_tokens = 262144
max_total_tokens = 262144
retain_traces = false
rich = false

[client]
type = "eval"
base_url = "http://localhost.invalid/v1"
api_key_var = "OPENAI_API_KEY"
capture_model_io = true
outbound_body_denylist = ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
max_connections = 4
max_keepalive_connections = 4
timeout = 43200
connect_timeout = 120
headers = {{}}

[sampling]
reasoning_effort = "max"
max_tokens = 262144

[sampling.chat_template_kwargs]
enable_thinking = true
preserve_thinking = true

[taskset]
id = "terminal-bench-vmvm"
task_file = "{universe}"
task_file_sha256 = "{universe_sha256}"
dataset_dir = "{dataset}"
use_declared_images = true

[harness]
config_overrides = ["model.model_kwargs.timeout=43200"]
[harness.runtime]
type = "vmvm"
session_timeout = 43200

[timeout]
rollout = 36000
'''
    )
    plan_dir = tmp_path / "plan"
    create_plan(universe, universe_sha256, base, plan_dir, shard_size=1)
    plan = plan_dir / "plan.json"
    return plan, _sha256(plan)


def _make_dataset_archive(tmp_path: Path) -> tuple[Path, Path, str, str]:
    dataset = tmp_path / "dataset"
    case = dataset / "opaque"
    case.mkdir(parents=True)
    (case / "task.toml").write_text("version = 1\n")
    archive = tmp_path / "dataset.tar"
    with tarfile.open(archive, "w") as handle:
        handle.add(dataset, arcname="tasks")
    content_sha256 = launcher._tree_digest(dataset)
    assert launcher._archive_tasks_tree_digest(archive) == content_sha256
    return dataset, archive, _sha256(archive), content_sha256


def _generation() -> dict[str, object]:
    backend = hashlib.sha256(b"http://worker.invalid:8000/v1").hexdigest()
    return {
        "schema_version": 2,
        "coordinator": {
            "slurm_job_id": "901",
            "started_at": "2026-09-17T00:00:00Z",
        },
        "proxy": {
            "slurm_job_id": "902",
            "first_ready_at": "2026-09-17T00:30:00Z",
        },
        "routes": [
            {
                "slurm_job_id": "903",
                "started_at": "2026-09-17T01:00:00Z",
                "backend_sha256": f"backend-sha256:{backend}",
            }
        ],
    }


def _make_bindings(
    tmp_path: Path,
    *,
    dataset: Path,
    dataset_archive: Path,
    dataset_archive_sha256: str,
    dataset_content_sha256: str,
    with_telemetry: bool = False,
) -> dict[str, object]:
    deployment_id = "deployment-test"
    deployment_dir = tmp_path / deployment_id
    deployment_dir.mkdir()
    spec = deployment_dir / "spec.yaml"
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n")
    policy_config = deployment_dir / "proxy_litellm_config.yaml"
    policy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n")
    proxy = deployment_dir / "proxy_info.json"
    proxy.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 8100,
                "url": "http://127.0.0.1:8100",
                "api_key": "unit-test-only-secret",
                "model": "Kimi-K3",
                "proxy_jobid": "902",
                "extras": {
                    "proxy_type": "litellm",
                    "sticky": True,
                    "redis_port": 6379,
                },
            }
        )
        + "\n"
    )
    endpoint = load_deployment_endpoint(
        proxy,
        deployment_id=deployment_id,
        expected_model="Kimi-K3",
        deployment_spec=spec,
        expected_proxy_info_sha256=_sha256(proxy),
    ).binding
    generation = _generation()
    policy = {
        "schema_version": 1,
        "request_timeout": 43200,
        "num_retries": 0,
        "proxy_litellm_config": _record(policy_config),
    }
    readiness = tmp_path / "readiness.json"
    readiness_value = {
        "schema_version": 1,
        "state": "passed",
        "deployment": deployment_id,
        "observed_spec_sha256": _sha256(spec),
        "expected_routes": 1,
        "endpoint": endpoint,
        "proxy_policy": policy,
        "serving_route_generation": generation,
        "last_status": {
            "schema_version": 4,
            "deployment_id": deployment_id,
            "phase": "serving",
            "desired": 1,
            "ready": 1,
            "running_not_ready": 0,
            "pending": 0,
            "coordinator_incarnation": generation["coordinator"],
            "coord_ticks_completed": 10,
            "serving_route_generation": generation,
        },
        "probe": {
            "ok": True,
            "endpoint_authority_sha256": endpoint["authority_sha256"],
            "coverage": {
                "ok": True,
                "expected_routes": 1,
                "discovered_routes": 1,
                "backends": [generation["routes"][0]["backend_sha256"]],
            },
        },
    }
    readiness.write_text(json.dumps(readiness_value) + "\n")

    run_dir = tmp_path / "smoke"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    source_config = inputs / "source_config.toml"
    source_config.write_text("source = true\n")
    task_file = inputs / "task_file.txt"
    task_file.write_text("synthetic-smoke-case\n")
    resolved_config = run_dir / "config.toml"
    resolved_config.write_text(
        f'''model = "Kimi-K3"
num_tasks = 1
num_rollouts = 1
max_concurrent = 4
multiplex = 4
max_input_tokens = 262144
max_output_tokens = 262144
max_total_tokens = 262144
output_dir = "{run_dir}"
retain_traces = false
rich = false

[client]
type = "eval"
base_url = "http://127.0.0.1:8100/v1"
api_key_var = "OPENAI_API_KEY"
capture_model_io = true
outbound_body_denylist = ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
max_connections = 4
max_keepalive_connections = 4
headers = {{}}

[sampling]
reasoning_effort = "max"
max_tokens = 262144

[sampling.chat_template_kwargs]
enable_thinking = true
preserve_thinking = true

[taskset]
id = "terminal-bench-vmvm"
task_file = "{task_file}"
task_file_sha256 = "{_sha256(task_file)}"
dataset_dir = "{dataset}"
use_declared_images = true

[harness]
[harness.runtime]
type = "vmvm"
'''
    )
    manifest = inputs / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "config": {
                    "source": str(source_config),
                    "snapshot": str(source_config),
                    "sha256": _sha256(source_config),
                },
                "task_file": {
                    "source": str(task_file),
                    "snapshot": str(task_file),
                    "sha256": _sha256(task_file),
                },
            }
        )
        + "\n"
    )
    artifacts: dict[str, dict[str, object]] = {}
    for name, relative in launcher.SMOKE_ARTIFACT_PATHS.items():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if name not in {
            "eval_run_identity",
            "eval_invocations",
            "route_guard_success",
            "config",
            "inputs_manifest",
            "provenance",
        }:
            path.write_text(f"{name}\n")
            artifacts[name] = _record(path)
    artifacts["config"] = _record(resolved_config)
    artifacts["inputs_manifest"] = _record(manifest)

    identity = {
        "schema_version": 1,
        "role": "smoke",
        "source": {
            "project_root": str(tmp_path / "source"),
            "prime_rl_commit": "a" * 40,
            "prime_rl_tree_sha256": launcher.CLEAN_TREE_SHA256,
            "verifiers_commit": "b" * 40,
            "verifiers_tree_sha256": launcher.CLEAN_TREE_SHA256,
            "renderers_commit": "c" * 40,
            "renderers_tree_sha256": launcher.CLEAN_TREE_SHA256,
            "vmvm_tb_v2_sha256": "d" * 64,
        },
        "config": {
            "source": _record(source_config),
            "resolved": _record(resolved_config),
        },
        "inputs": {
            "manifest": _record(manifest),
            "task_file": _record(task_file, count=1),
            "image_manifest": None,
        },
        "dataset": {
            "kind": "archive",
            "path": str(dataset),
            "revision": None,
            "archive": {
                "path": str(dataset_archive),
                "sha256": dataset_archive_sha256,
            },
            "content_sha256": dataset_content_sha256,
        },
        "contract": {
            "model": "Kimi-K3",
            "pass_at_1": True,
            "num_rollouts": 1,
            "reasoning_effort": "max",
            "thinking": {"enable_thinking": True, "preserve_thinking": True},
            "context_tokens": {
                "max_input_tokens": 262_144,
                "max_output_tokens": 262_144,
                "max_total_tokens": 262_144,
            },
            "sampling_max_tokens": 262_144,
            "capture_model_io": True,
            "outbound_body_denylist": [
                "logprobs",
                "prompt_logprobs",
                "return_token_ids",
                "top_logprobs",
            ],
            "retain_traces": False,
        },
        "execution": {
            "rollout_concurrency": 4,
            "multiplex": 4,
            "http_max_connections": 4,
            "http_max_keepalive_connections": 4,
            "runtime": {"type": "vmvm"},
            "vmvm_environment": {
                "vacli_bin": launcher.DEFAULT_VACLI_BIN,
                "lease_start_concurrency": 2,
                "lease_retries": 20,
                "max_pull_retries": 20,
                "image_pull_timeout_sec": 3600,
                "container_privileged": True,
            },
        },
        "deployment": {
            "id": deployment_id,
            "endpoint": endpoint,
            "serving_route_generation": generation,
            "proxy_policy": policy,
            "routing": {"deployment_id": None, "headers": {}},
            "spec": _record(spec),
            "readiness_checkpoint": _record(readiness),
            "smoke_checkpoint": None,
            "promotion_certificate": None,
        },
    }
    identity_sha256 = hashlib.sha256(canonical_json(identity)).hexdigest()
    identity_path = run_dir / "eval_run_identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "identity": identity,
            }
        )
        + "\n"
    )
    artifacts["eval_run_identity"] = _record(identity_path)
    provenance = run_dir / "provenance.txt"
    provenance.write_text(
        "".join(
            f"{key}={value}\n"
            for key, value in {
                "prime_rl": "a" * 40,
                "prime_rl_tree": launcher.CLEAN_TREE_SHA256,
                "verifiers": "b" * 40,
                "verifiers_tree": launcher.CLEAN_TREE_SHA256,
                "renderers": "c" * 40,
                "renderers_tree": launcher.CLEAN_TREE_SHA256,
                "vmvm_tb_v2": "d" * 64,
                "deployment_id": deployment_id,
                "deployment_endpoint_authority_sha256": endpoint["authority_sha256"],
                "deployment_proxy_info_sha256": endpoint["proxy_info"]["sha256"],
                "eval_run_role": "smoke",
                "eval_run_identity_sha256": identity_sha256,
                "host": "unit-test-host",
                "slurm_job_id": "904",
                "approval_task_file_sha256": _sha256(task_file),
                "approval_task_count": "1",
            }.items()
        )
    )
    artifacts["provenance"] = _record(provenance)
    invocation_path = run_dir / "eval_invocations.jsonl"
    invocation_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "eval_run_identity_sha256": identity_sha256,
                "role": "smoke",
                "resume": False,
                "host": "unit-test-host",
                "slurm_job_id": "904",
            }
        )
        + "\n"
    )
    artifacts["eval_invocations"] = _record(invocation_path)
    if with_telemetry:
        telemetry = run_dir / launcher.OPTIONAL_SMOKE_ARTIFACT_PATHS["concurrency_telemetry"]
        observations = {
            "active_vmvm_runtimes_at_publish": 0,
            "counter_violations": 0,
            "lease_start_attempts": 1,
            "lease_start_finishes": 1,
            "lease_startups_at_publish": 0,
            "lease_tunnels_ready": 1,
            "peak_active_vmvm_runtimes": 1,
            "peak_concurrent_lease_startups": 1,
            "vmvm_runtime_ready": 1,
            "vmvm_runtime_starts": 1,
            "vmvm_runtime_stops": 1,
        }
        telemetry_body = {
            "schema_version": 1,
            "state": "complete",
            "eval_run_identity_sha256": identity_sha256,
            "eval_run_role": "smoke",
            "slurm_job_id": "904",
            "process_id": 1,
            "measurement_scope": "single_evaluator_process",
            "observations": observations,
        }
        telemetry.write_text(
            json.dumps(
                {
                    **telemetry_body,
                    "concurrency_telemetry_sha256": hashlib.sha256(canonical_json(telemetry_body)).hexdigest(),
                }
            )
            + "\n"
        )
        telemetry.chmod(0o400)
        artifacts["concurrency_telemetry"] = _record(telemetry)
    receipt_path = run_dir / "route_guard_success.json"
    receipt_artifacts = {name: artifacts[name] for name in ("eval_run_identity", "eval_invocations", "results")}
    if with_telemetry:
        receipt_artifacts["concurrency_telemetry"] = artifacts["concurrency_telemetry"]
    receipt_body = {
        "schema_version": 2 if with_telemetry else 1,
        "state": "passed",
        "evaluator_exit_code": 0,
        "completed_at": "2026-09-17T02:00:00Z",
        "eval_run_role": "smoke",
        "eval_run_identity_sha256": identity_sha256,
        "deployment": {
            "id": deployment_id,
            "spec_sha256": _sha256(spec),
            "readiness_checkpoint": _record(readiness),
            "endpoint": endpoint,
            "serving_route_generation": generation,
            "proxy_policy": policy,
        },
        "artifacts": receipt_artifacts,
    }
    receipt_path.write_text(
        json.dumps(
            {
                **receipt_body,
                "guard_success_receipt_sha256": hashlib.sha256(canonical_json(receipt_body)).hexdigest(),
            }
        )
        + "\n"
    )
    artifacts["route_guard_success"] = _record(receipt_path)
    artifacts["readiness_checkpoint"] = _record(readiness)
    artifacts["proxy_info"] = _record(proxy)
    smoke = run_dir / "smoke_checkpoint.json"
    smoke_body = {
        "schema_version": 1,
        "state": "passed",
        "ok": True,
        "eval_run_identity_sha256": identity_sha256,
        "deployment_id": deployment_id,
        "deployment_spec_sha256": _sha256(spec),
        "readiness_checkpoint_sha256": _sha256(readiness),
        "deployment": {"id": deployment_id, "spec_sha256": _sha256(spec)},
        "endpoint": endpoint,
        "serving_route_generation": generation,
        "proxy_policy": policy,
        "qualified_execution": {
            "rollout_concurrency": 4,
            "multiplex": 4,
            "http_max_connections": 4,
            "http_max_keepalive_connections": 4,
            "lease_start_concurrency": 2,
        },
        "audit_policy": {
            "expected_traces": 1,
            "rollouts_per_task": 1,
            "require_reasoning": True,
            "require_model_io": True,
            "model_io_contract": launcher.EXPECTED_MODEL_IO_CONTRACT,
            "require_token_data": False,
            "require_logprobs": False,
            "max_sequence_tokens": 262_144,
        },
        "counts": {
            "traces": 1,
            "tasks": 1,
            "sampled_tokens": 1,
            "model_io_turns": 1,
            "trace_failures": 0,
            "global_problems": 0,
        },
        "artifacts": artifacts,
    }
    if with_telemetry:
        smoke_body["observed_concurrency"] = {
            "active_rollout_signal": "completed_trace_lifecycle_timing_overlap",
            "lease_start_signal": "vacli_lease_start_semaphore_holders",
            "peak_active_rollouts_lower_bound": 1,
            "peak_concurrent_lease_startups": 1,
            "required_peak_active_rollouts_lower_bound": 1,
            "required_peak_concurrent_lease_startups": 1,
        }
    smoke_value = {
        **smoke_body,
        "smoke_checkpoint_sha256": hashlib.sha256(canonical_json(smoke_body)).hexdigest(),
    }
    smoke.write_text(json.dumps(smoke_value) + "\n")
    return {
        "deployment_id": deployment_id,
        "deployment_spec_path": spec,
        "deployment_spec_sha256": _sha256(spec),
        "readiness_path": readiness,
        "readiness_sha256": _sha256(readiness),
        "proxy_info_path": proxy,
        "proxy_info_sha256": _sha256(proxy),
        "smoke_checkpoint_path": smoke,
        "smoke_checkpoint_sha256": _sha256(smoke),
    }


def _fixture(tmp_path: Path, monkeypatch, *, with_telemetry: bool = False):
    dataset, archive, archive_sha256, content_sha256 = _make_dataset_archive(tmp_path)
    plan, plan_sha256 = _make_plan(tmp_path, dataset)
    project = tmp_path / "project"
    workflow = project / "user/tianhaowu/terminal_bench_vmvm"
    workflow.mkdir(parents=True)
    (workflow / "run_eval.sbatch").write_text("#!/bin/bash\n")
    revisions = {"prime_rl": "a" * 40, "verifiers": "b" * 40, "renderers": "c" * 40}
    monkeypatch.setattr(launcher, "validate_clean_project", lambda *_args, **_kwargs: revisions)
    monkeypatch.setattr(launcher, "_require_tmux_launcher", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(launcher, "_validate_identity_source", lambda *_args, **_kwargs: None)
    return {
        "project_dir": project,
        "project_revision": "a" * 40,
        "plan_path": plan,
        "plan_sha256": plan_sha256,
        "shard_indices": [0, 1, 2, 3],
        "output_root": tmp_path / "wave",
        **_make_bindings(
            tmp_path,
            dataset=dataset,
            dataset_archive=archive,
            dataset_archive_sha256=archive_sha256,
            dataset_content_sha256=content_sha256,
            with_telemetry=with_telemetry,
        ),
        "dataset_archive_path": archive,
        "dataset_archive_sha256": archive_sha256,
        "dataset_content_sha256": content_sha256,
        "ambient_env": {},
    }


def _rewrite_smoke(arguments: dict[str, object], changed_artifacts: tuple[str, ...]) -> None:
    smoke_path = arguments["smoke_checkpoint_path"]
    assert isinstance(smoke_path, Path)
    value = json.loads(smoke_path.read_text())
    for name in changed_artifacts:
        artifact_path = Path(value["artifacts"][name]["path"])
        value["artifacts"][name]["sha256"] = _sha256(artifact_path)
    body = {key: item for key, item in value.items() if key != "smoke_checkpoint_sha256"}
    value["smoke_checkpoint_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
    smoke_path.write_text(json.dumps(value) + "\n")
    arguments["smoke_checkpoint_sha256"] = _sha256(smoke_path)


@pytest.mark.parametrize("with_telemetry", [False, True])
def test_dry_run_is_private_exact_and_never_submits(tmp_path: Path, monkeypatch, with_telemetry: bool):
    arguments = _fixture(tmp_path, monkeypatch, with_telemetry=with_telemetry)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("command runner must not be called during dry run")

    wave = launch_wave(**arguments, dry_run=True, command_runner=forbidden)

    output = arguments["output_root"]
    assert wave["state"] == "validated"
    assert wave["wave_size"] == 4
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    for job in wave["jobs"]:
        raw = Path(job["environment"]["path"]).read_bytes()
        values = dict(record.decode().split("=", 1) for record in raw.split(b"\0") if record)
        assert values["EVAL_RUN_ROLE"] == "tb4"
        assert values["EVAL_EXPECTED_MODEL"] == "Kimi-K3"
        assert values["EVAL_EXPECTED_PRIME_RL_REVISION"] == "a" * 40
        assert values["EVAL_CONFIG_SHA256"] == job["config_sha256"]
        assert {key: values[key] for key in EXPECTED_VMVM_ENV} == EXPECTED_VMVM_ENV
        assert "RESUME_DIR" not in values
        assert "EVAL_MODEL" not in values
        assert "INFERENCE_BASE_URL" not in values
        assert "OPENAI_API_KEY" not in values


def test_fake_submit_uses_existing_run_eval_and_empty_client_environment(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=f"{1000 + len(calls)}\n", stderr="")

    wave = launch_wave(**arguments, dry_run=False, command_runner=fake_runner)

    assert wave["state"] == "submitted"
    assert len(calls) == 4
    for argv, kwargs in calls:
        assert argv[0] == launcher.DEFAULT_SBATCH
        assert argv[-1].endswith("/run_eval.sbatch")
        assert any(value.startswith("--export-file=") for value in argv)
        assert kwargs["env"] == {}
        assert kwargs["timeout"] == launcher.DEFAULT_SUBMISSION_TIMEOUT_SECONDS


def test_signal_stops_at_submission_boundary_without_an_extra_job(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    calls = 0
    checks = 0

    def stop_requested():
        nonlocal checks
        checks += 1
        return checks > 2

    def fake_runner(argv, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, stdout="1001\n", stderr="")

    with pytest.raises(launcher.WaveSubmissionInterrupted, match="submission_interrupted"):
        launch_wave(
            **arguments,
            dry_run=False,
            command_runner=fake_runner,
            stop_requested=stop_requested,
        )

    assert calls == 1
    metadata = json.loads((arguments["output_root"] / "wave.json").read_text())
    assert metadata["state"] == "submission_interrupted"
    assert metadata["jobs"][0]["slurm_job_id"] == "1001"
    assert all(job["submission_token"] is None for job in metadata["jobs"][1:])


def test_sbatch_timeout_preserves_recoverable_submission_intent(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    with pytest.raises(
        launcher.WaveSubmissionOutcomeUnknown,
        match="sbatch_submission_outcome_unknown",
    ):
        launch_wave(**arguments, dry_run=False, command_runner=timeout)

    metadata = json.loads((arguments["output_root"] / "wave.json").read_text())
    assert metadata["state"] == "submitting"
    assert metadata["jobs"][0]["submission_token"] is not None
    assert metadata["jobs"][0]["slurm_job_id"] is None
    assert all(job["submission_token"] is None for job in metadata["jobs"][1:])


def test_rejects_resume_existing_output_and_invalid_wave(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    output = arguments["output_root"]
    with pytest.raises(WaveLaunchError, match="resume_forbidden"):
        launch_wave(**{**arguments, "ambient_env": {"RESUME_DIR": ""}}, dry_run=True)
    output.mkdir()
    with pytest.raises(WaveLaunchError, match="output_root_exists"):
        launch_wave(**arguments, dry_run=True)
    output.rmdir()
    with pytest.raises(WaveLaunchError, match="shard_indices_invalid"):
        launch_wave(**{**arguments, "shard_indices": [0, 1, 2, 3, 4]}, dry_run=True)
    with pytest.raises(WaveLaunchError, match="shard_indices_invalid"):
        launch_wave(**{**arguments, "shard_indices": [0, 0]}, dry_run=True)
    with pytest.raises(WaveLaunchError, match="project_revision_mismatch"):
        launch_wave(**{**arguments, "project_revision": "f" * 40}, dry_run=True)


def test_submit_requires_exact_tmux_pane():
    def fake_runner(argv, **_kwargs):
        assert argv[:3] == ["tmux", "display-message", "-p"]
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="wrong-session:Launcher.0\n",
            stderr="",
        )

    with pytest.raises(WaveLaunchError, match="submission_requires_tmux_launcher"):
        launcher._require_tmux_launcher(
            {"TMUX_PANE": "%9"},
            runner=fake_runner,
        )


def test_rejects_dangling_output_symlink_and_plan_swap(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    output = arguments["output_root"]
    output.symlink_to(tmp_path / "missing-target")
    with pytest.raises(WaveLaunchError, match="output_root_exists"):
        launch_wave(**arguments, dry_run=True)
    output.unlink()

    real_load_plan = launcher.load_plan

    def swapping_load_plan(path: Path):
        loaded = real_load_plan(path)
        path.write_bytes(path.read_bytes() + b" ")
        return loaded

    monkeypatch.setattr(launcher, "load_plan", swapping_load_plan)
    with pytest.raises(WaveLaunchError, match="plan_sha256_mismatch"):
        launch_wave(**arguments, dry_run=True)


def test_partial_fake_submission_is_recorded_and_stops(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    calls = 0

    def fake_runner(argv, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="private detail")
        return subprocess.CompletedProcess(argv, 0, stdout="1001\n", stderr="")

    with pytest.raises(WaveLaunchError, match="wave_submission_incomplete"):
        launch_wave(**arguments, dry_run=False, command_runner=fake_runner)

    assert calls == 2
    metadata = json.loads((arguments["output_root"] / "wave.json").read_text())
    assert metadata["state"] == "partial_submission_failed"
    assert metadata["jobs"][0]["slurm_job_id"] == "1001"
    assert all(job["slurm_job_id"] is None for job in metadata["jobs"][1:])


def test_environment_is_rehashed_after_submission_intent_is_persisted(
    tmp_path: Path,
    monkeypatch,
):
    arguments = _fixture(tmp_path, monkeypatch)
    real_replace = launcher._replace_private_json
    changed = False

    def replace_and_tamper(path: Path, value: dict[str, object]):
        nonlocal changed
        digest = real_replace(path, value)
        jobs = value.get("jobs")
        if not changed and isinstance(jobs, list) and jobs and jobs[0].get("submission_token") is not None:
            environment = Path(jobs[0]["environment"]["path"])
            environment.write_bytes(environment.read_bytes() + b"tamper\0")
            changed = True
        return digest

    monkeypatch.setattr(launcher, "_replace_private_json", replace_and_tamper)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sbatch must not run after environment mutation")

    with pytest.raises(WaveLaunchError, match="wave_submission_incomplete"):
        launch_wave(**arguments, dry_run=False, command_runner=forbidden)

    assert changed is True


def test_rejects_semantically_tampered_guard_receipt(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    smoke = json.loads(Path(arguments["smoke_checkpoint_path"]).read_text())
    receipt_path = Path(smoke["artifacts"]["route_guard_success"]["path"])
    receipt = json.loads(receipt_path.read_text())
    receipt["evaluator_exit_code"] = 1
    receipt_body = {key: item for key, item in receipt.items() if key != "guard_success_receipt_sha256"}
    receipt["guard_success_receipt_sha256"] = hashlib.sha256(canonical_json(receipt_body)).hexdigest()
    receipt_path.write_text(json.dumps(receipt) + "\n")
    _rewrite_smoke(arguments, ("route_guard_success",))

    with pytest.raises(WaveLaunchError, match="smoke_guard_receipt_invalid"):
        launch_wave(**arguments, dry_run=True)


def test_rejects_tampered_identity_reference(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch)
    smoke = json.loads(Path(arguments["smoke_checkpoint_path"]).read_text())
    identity_path = Path(smoke["artifacts"]["eval_run_identity"]["path"])
    identity = json.loads(identity_path.read_text())["identity"]
    source_config = Path(identity["config"]["source"]["path"])
    source_config.write_text("changed = true\n")

    with pytest.raises(WaveLaunchError, match="smoke_identity_config_sha256_mismatch"):
        launch_wave(**arguments, dry_run=True)


def test_rejects_semantically_tampered_telemetry(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch, with_telemetry=True)
    smoke_path = Path(arguments["smoke_checkpoint_path"])
    smoke = json.loads(smoke_path.read_text())
    telemetry_path = Path(smoke["artifacts"]["concurrency_telemetry"]["path"])
    telemetry_path.chmod(0o600)
    telemetry = json.loads(telemetry_path.read_text())
    telemetry["observations"]["counter_violations"] = 1
    telemetry_body = {key: item for key, item in telemetry.items() if key != "concurrency_telemetry_sha256"}
    telemetry["concurrency_telemetry_sha256"] = hashlib.sha256(canonical_json(telemetry_body)).hexdigest()
    telemetry_path.write_text(json.dumps(telemetry) + "\n")
    telemetry_path.chmod(0o400)

    receipt_path = Path(smoke["artifacts"]["route_guard_success"]["path"])
    receipt = json.loads(receipt_path.read_text())
    receipt["artifacts"]["concurrency_telemetry"]["sha256"] = _sha256(telemetry_path)
    receipt_body = {key: item for key, item in receipt.items() if key != "guard_success_receipt_sha256"}
    receipt["guard_success_receipt_sha256"] = hashlib.sha256(canonical_json(receipt_body)).hexdigest()
    receipt_path.write_text(json.dumps(receipt) + "\n")
    _rewrite_smoke(arguments, ("concurrency_telemetry", "route_guard_success"))

    with pytest.raises(WaveLaunchError, match="smoke_concurrency_telemetry_invalid"):
        launch_wave(**arguments, dry_run=True)


def test_v2_smoke_allows_unspecified_concurrency_minima(tmp_path: Path, monkeypatch):
    arguments = _fixture(tmp_path, monkeypatch, with_telemetry=True)
    smoke_path = Path(arguments["smoke_checkpoint_path"])
    smoke = json.loads(smoke_path.read_text())
    smoke["observed_concurrency"]["required_peak_active_rollouts_lower_bound"] = None
    smoke["observed_concurrency"]["required_peak_concurrent_lease_startups"] = None
    body = {key: item for key, item in smoke.items() if key != "smoke_checkpoint_sha256"}
    smoke["smoke_checkpoint_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
    smoke_path.write_text(json.dumps(smoke) + "\n")
    arguments["smoke_checkpoint_sha256"] = _sha256(smoke_path)

    assert launch_wave(**arguments, dry_run=True)["state"] == "validated"


def test_large_archive_hashing_is_streaming(tmp_path: Path):
    artifact = tmp_path / "large.bin"
    with artifact.open("wb") as handle:
        handle.seek(launcher.MAX_ARTIFACT_BYTES + 1024)
        handle.write(b"x")
    digest = _sha256(artifact)
    pinned = launcher._stable_artifact(artifact, digest, label="large")
    assert pinned.raw is None
    assert pinned.sha256 == digest


def test_main_wraps_plan_validation_without_traceback(tmp_path: Path, capsys):
    plan = tmp_path / "plan.json"
    _private_write(plan, b"not-json\n")
    result = launcher.main(
        [
            "--project-dir",
            str(tmp_path),
            "--project-revision",
            "a" * 40,
            "--plan",
            str(plan),
            "--plan-sha256",
            _sha256(plan),
            "--shard-index",
            "0",
            "--output-root",
            str(tmp_path / "output"),
            "--deployment-id",
            "deployment-test",
            "--deployment-spec",
            str(tmp_path / "spec.yaml"),
            "--deployment-spec-sha256",
            "a" * 64,
            "--readiness-checkpoint",
            str(tmp_path / "readiness.json"),
            "--readiness-checkpoint-sha256",
            "b" * 64,
            "--proxy-info",
            str(tmp_path / "proxy_info.json"),
            "--proxy-info-sha256",
            "c" * 64,
            "--smoke-checkpoint",
            str(tmp_path / "smoke.json"),
            "--smoke-checkpoint-sha256",
            "d" * 64,
            "--dataset-revision",
            "e" * 40,
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "tb4_shard_wave_error:plan_invalid\n"
    assert "Traceback" not in captured.err


def test_archive_helper_ignores_non_task_members(tmp_path: Path):
    archive = tmp_path / "dataset.tar"
    with tarfile.open(archive, "w") as handle:
        info = tarfile.TarInfo("metadata.txt")
        payload = b"ignored"
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    with pytest.raises(WaveLaunchError, match="dataset_archive_invalid"):
        launcher._archive_tasks_tree_digest(archive)
