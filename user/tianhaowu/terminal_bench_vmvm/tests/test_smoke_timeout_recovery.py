from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import smoke_qualification as qualification
import smoke_timeout_recovery as recovery
import tomli_w
from snapshot_eval_inputs import snapshot
from validate_task_approval import validate_approval


def _digest(value: dict) -> str:
    return hashlib.sha256(recovery.canonical_json(value)).hexdigest()


def _trace(trace_id: str, slug: str) -> dict:
    request = {
        "model": "Kimi-K3",
        "reasoning_effort": "max",
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        "messages": [{"role": "user", "content": "synthetic"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "shell",
                    "description": "synthetic",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }
    message = {
        "role": "assistant",
        "content": "done",
        "reasoning_content": "reasoning",
    }
    response = {
        "id": "response",
        "object": "chat.completion",
        "created": 1,
        "model": "Kimi-K3",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    return {
        "id": trace_id,
        "task": {"slug": slug},
        "is_completed": True,
        "stop_condition": "max_turns",
        "errors": [],
        "nodes": [
            {
                "parent": None,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "user", "content": "synthetic"},
            },
            {
                "parent": 0,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": message,
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
                "finish_reason": "stop",
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _digest(request), "body": request},
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _digest(response),
                        "body": response,
                    },
                },
            },
        ],
    }


def _row(trace: dict) -> recovery.TraceRow:
    return recovery.TraceRow(raw=json.dumps(trace, sort_keys=True).encode() + b"\n", trace=trace)


def _artifact(path: Path, raw: bytes) -> recovery.FileArtifact:
    path.write_bytes(raw)
    return recovery.FileArtifact(path.resolve(), hashlib.sha256(raw).hexdigest(), raw)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_repository(repository: Path) -> str:
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "smoke-recovery@example.invalid")
    _git(repository, "config", "user.name", "Smoke Recovery Test")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "fixture")
    return _git(repository, "rev-parse", "HEAD")


def test_selector_derives_only_missing_line_and_keeps_identifiers_out_of_attestation(tmp_path: Path) -> None:
    manifest = b"private-task-alpha\nprivate-task-beta\n"
    selection = recovery.derive_selection(manifest, [_row(_trace("private-trace", "private-task-beta"))])

    assert selection.retained_index == 1
    assert selection.recovery_index == 0
    assert selection.recovery_entry.raw == b"private-task-alpha\n"
    assert selection.missing_rows == 1
    assert selection.harness_timeout_rows == 0

    source = {
        "identity_sha256": "a" * 64,
        "identity": {
            "deployment": {
                "id": "deployment",
                "spec": {"path": "/spec", "sha256": "b" * 64},
                "readiness_checkpoint": {"path": "/ready", "sha256": "c" * 64},
                "endpoint": {"authority_sha256": "d" * 64},
                "serving_route_generation": {"schema_version": 2},
                "proxy_policy": {"request_timeout": 43_200},
            }
        },
        "results_artifact": recovery.FileArtifact(Path("/results"), "e" * 64),
        "identity_artifact": recovery.FileArtifact(Path("/identity"), "f" * 64),
        "invocations_artifact": recovery.FileArtifact(Path("/invocations"), "1" * 64),
        "receipt_artifact": recovery.FileArtifact(Path("/receipt"), "2" * 64),
    }
    body = recovery._selection_body(
        source=source,
        original_manifest=recovery.FileArtifact(Path("/manifest"), "3" * 64),
        recovery_task=recovery.FileArtifact(Path("/approval"), "4" * 64),
        recovery_config_template=recovery.FileArtifact(Path("/template"), "5" * 64),
        recovery_config=recovery.FileArtifact(Path("/config"), "6" * 64),
        recovery_policy={"closure_sha256": "7" * 64},
        recovery_run_dir=Path("/fresh/run"),
        selection=selection,
    )
    encoded = json.dumps(body, sort_keys=True)
    assert "private-task-alpha" not in encoded
    assert "private-task-beta" not in encoded
    assert "private-trace" not in encoded


def test_selector_accepts_only_exact_harness_timeout_for_second_row() -> None:
    manifest = b"private-task-alpha\nprivate-task-beta\n"
    clean = _trace("trace-clean", "private-task-alpha")
    timed_out = _trace("trace-timeout", "private-task-beta")
    timed_out["stop_condition"] = "harness_timeout"

    selection = recovery.derive_selection(manifest, [_row(clean), _row(timed_out)])

    assert selection.retained_index == 0
    assert selection.recovery_index == 1
    assert selection.harness_timeout_rows == 1
    assert selection.missing_rows == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "two_clean",
        "other_infrastructure_stop",
        "duplicate_task",
        "trace_error",
        "non_list_empty_errors",
        "normalized_provider_response",
    ],
)
def test_selector_fails_closed_on_ambiguous_or_ineligible_sources(mutation: str) -> None:
    manifest = b"private-task-alpha\nprivate-task-beta\n"
    first = _trace("trace-a", "private-task-alpha")
    second = _trace("trace-b", "private-task-beta")
    if mutation == "other_infrastructure_stop":
        second["stop_condition"] = "cancelled"
    elif mutation == "duplicate_task":
        second["task"]["slug"] = "private-task-alpha"
        second["stop_condition"] = "harness_timeout"
    elif mutation == "trace_error":
        second["errors"] = [{"type": "private-error"}]
        second["stop_condition"] = "harness_timeout"
    elif mutation == "non_list_empty_errors":
        second["errors"] = {}
        second["stop_condition"] = "harness_timeout"
    elif mutation == "normalized_provider_response":
        second = None
        first["nodes"][1]["model_io"]["response"]["kind"] = "normalized_stream_response"
    rows = [_row(first)] if second is None else [_row(first), _row(second)]

    with pytest.raises(recovery.SmokeRecoveryError):
        recovery.derive_selection(manifest, rows)


def test_composite_is_exactly_disjoint_and_ordered_by_original_manifest(tmp_path: Path) -> None:
    manifest_raw = b"private-task-alpha\nprivate-task-beta\n"
    retained = _trace("trace-b", "private-task-beta")
    selection = recovery.derive_selection(manifest_raw, [_row(retained)])
    recovered = _trace("trace-a", "private-task-alpha")
    original_manifest = _artifact(tmp_path / "original.txt", manifest_raw)
    recovery_task = _artifact(tmp_path / "one.txt", b"private-task-alpha\n")
    recovery_results = _artifact(tmp_path / "recovery.jsonl", _row(recovered).raw)

    combined, summary, recovery_row = recovery._validate_combined_rows(
        original_manifest,
        selection,
        recovery_task,
        recovery_results,
    )

    assert [_trace_row.trace["task"]["slug"] for _trace_row in recovery._strict_jsonl(combined, label="test")] == [
        "private-task-alpha",
        "private-task-beta",
    ]
    assert summary["traces"] == summary["tasks"] == 2
    assert recovery_row.trace["id"] == "trace-a"


def test_composite_rejects_duplicate_trace_or_wrong_recovery_task(tmp_path: Path) -> None:
    manifest_raw = b"private-task-alpha\nprivate-task-beta\n"
    retained = _trace("same-trace", "private-task-alpha")
    selection = recovery.derive_selection(manifest_raw, [_row(retained)])
    original_manifest = _artifact(tmp_path / "original.txt", manifest_raw)
    expected_task = _artifact(tmp_path / "one.txt", b"private-task-beta\n")

    duplicate = _artifact(
        tmp_path / "duplicate.jsonl",
        _row(_trace("same-trace", "private-task-beta")).raw,
    )
    with pytest.raises(recovery.SmokeRecoveryError, match="^composite_disjointness_invalid$"):
        recovery._validate_combined_rows(original_manifest, selection, expected_task, duplicate)

    wrong_task = _artifact(tmp_path / "wrong.txt", b"private-task-alpha\n")
    recovered = _artifact(
        tmp_path / "recovered.jsonl",
        _row(_trace("other-trace", "private-task-beta")).raw,
    )
    with pytest.raises(recovery.SmokeRecoveryError, match="^recovery_cardinality_invalid$"):
        recovery._validate_combined_rows(original_manifest, selection, wrong_task, recovered)

    missing_id_trace = _trace("other-trace", "private-task-beta")
    missing_id_trace.pop("id")
    missing_id = _artifact(tmp_path / "missing-id.jsonl", _row(missing_id_trace).raw)
    with pytest.raises(recovery.SmokeRecoveryError, match="^composite_disjointness_invalid$"):
        recovery._validate_combined_rows(original_manifest, selection, expected_task, missing_id)


def test_cli_error_output_never_echoes_untrusted_exception(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    secret = "https://private.invalid/private-task?key=secret"

    def fail(*_args, **_kwargs):
        raise recovery.SmokeRecoveryError(secret)

    monkeypatch.setattr(recovery, "create_selection", fail)
    result = recovery.main(
        [
            "select",
            "--source-run-dir",
            "/source",
            "--original-task-file",
            "/manifest",
            "--original-task-file-sha256",
            "a" * 64,
            "--recovery-config-template",
            "/template",
            "--recovery-config-template-sha256",
            "b" * 64,
            "--recovery-project-root",
            "/project",
            "--namespace",
            "/namespace",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "smoke_recovery_error:recovery_failed\n"
    assert secret not in captured.err


def test_recovery_launch_requires_unset_resume_and_fresh_exact_run_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = tmp_path / "namespace"
    namespace.mkdir()
    task = namespace / "approved_task.txt"
    task.write_text("private-task-alpha\n")
    digest = hashlib.sha256(task.read_bytes()).hexdigest()
    config = namespace / "config.toml"
    config.write_text('model = "Kimi-K3"\n')
    config_digest = hashlib.sha256(config.read_bytes()).hexdigest()
    spec = tmp_path / "spec.yaml"
    readiness = tmp_path / "readiness.json"
    proxy = tmp_path / "proxy.json"
    spec.write_text("spec\n")
    readiness.write_text("{}\n")
    proxy.write_text("{}\n")
    spec_record = {"path": str(spec.resolve()), "sha256": hashlib.sha256(spec.read_bytes()).hexdigest()}
    readiness_record = {
        "path": str(readiness.resolve()),
        "sha256": hashlib.sha256(readiness.read_bytes()).hexdigest(),
    }
    proxy_record = {"path": str(proxy.resolve()), "sha256": hashlib.sha256(proxy.read_bytes()).hexdigest()}
    policy = {
        "project_root": str(tmp_path.resolve()),
        "prime_rl_commit": "9" * 40,
        "closure_sha256": "8" * 64,
    }
    payload = {
        "selection_sha256": "a" * 64,
        "recovery": {"run_dir": str(namespace / "run")},
        "artifacts": {
            "recovery_task_file": {"path": str(task.resolve()), "sha256": digest},
            "recovery_config": {"path": str(config.resolve()), "sha256": config_digest},
        },
        "recovery_policy": policy,
        "deployment": {
            "id": "deployment",
            "spec": spec_record,
            "readiness_checkpoint": readiness_record,
            "endpoint": {"proxy_info": proxy_record},
        },
    }
    source = {
        "identity": {
            "source": {"project_root": str(tmp_path.resolve()), "prime_rl_commit": "9" * 40},
            "execution": {
                "vmvm_environment": {
                    "vacli_bin": "/vacli",
                    "lease_start_concurrency": 2,
                    "lease_retries": 20,
                    "max_pull_retries": 20,
                    "image_pull_timeout_sec": 3_600,
                    "container_privileged": True,
                }
            },
        }
    }
    monkeypatch.setattr(recovery, "_load_selection", lambda *_args, **_kwargs: (payload, object(), source))
    monkeypatch.setattr(recovery, "_recovery_source_binding", lambda *_args, **_kwargs: policy)

    result = recovery.validate_recovery_launch(
        namespace / "selection.json",
        namespace / "run",
        task,
        digest,
        config,
        config_digest,
        project_root=tmp_path,
        expected_prime_rl_commit="9" * 40,
        deployment_id="deployment",
        deployment_spec=spec,
        deployment_spec_sha256=spec_record["sha256"],
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=readiness_record["sha256"],
        proxy_info=proxy,
        proxy_info_sha256=proxy_record["sha256"],
        vacli_bin="/vacli",
        vacli_max_concurrent_leases="1",
        vacli_lease_retries="20",
        vacli_max_pull_retries="20",
        vacli_image_pull_timeout_seconds="3600",
        vacli_container_privileged="1",
        environ={},
    )
    assert result["counts"] == {"tasks": 1, "expected_traces": 1}

    with pytest.raises(recovery.SmokeRecoveryError, match="^resume_forbidden$"):
        recovery.validate_recovery_launch(
            namespace / "selection.json",
            namespace / "run",
            task,
            digest,
            config,
            config_digest,
            project_root=tmp_path,
            expected_prime_rl_commit="9" * 40,
            deployment_id="deployment",
            deployment_spec=spec,
            deployment_spec_sha256=spec_record["sha256"],
            readiness_checkpoint=readiness,
            readiness_checkpoint_sha256=readiness_record["sha256"],
            proxy_info=proxy,
            proxy_info_sha256=proxy_record["sha256"],
            vacli_bin="/vacli",
            vacli_max_concurrent_leases="1",
            vacli_lease_retries="20",
            vacli_max_pull_retries="20",
            vacli_image_pull_timeout_seconds="3600",
            vacli_container_privileged="1",
            environ={"RESUME_DIR": ""},
        )
    (namespace / "run").mkdir()
    with pytest.raises(recovery.SmokeRecoveryError, match="^recovery_launch_binding_invalid$"):
        recovery.validate_recovery_launch(
            namespace / "selection.json",
            namespace / "run",
            task,
            digest,
            config,
            config_digest,
            project_root=tmp_path,
            expected_prime_rl_commit="9" * 40,
            deployment_id="deployment",
            deployment_spec=spec,
            deployment_spec_sha256=spec_record["sha256"],
            readiness_checkpoint=readiness,
            readiness_checkpoint_sha256=readiness_record["sha256"],
            proxy_info=proxy,
            proxy_info_sha256=proxy_record["sha256"],
            vacli_bin="/vacli",
            vacli_max_concurrent_leases="1",
            vacli_lease_retries="20",
            vacli_max_pull_retries="20",
            vacli_image_pull_timeout_seconds="3600",
            vacli_container_privileged="1",
            environ={},
        )


def test_normalized_config_allows_only_reviewed_recovery_differences() -> None:
    original = {
        "model": "Kimi-K3",
        "num_tasks": 2,
        "max_concurrent": 2,
        "multiplex": 2,
        "max_turns": 8,
        "client": {"max_connections": 2, "max_keepalive_connections": 2, "timeout": 43_200},
        "taskset": {"task_file": "/two", "task_file_sha256": "a" * 64, "id": "terminal-bench-vmvm"},
        "harness": {"runtime": {"type": "vmvm", "session_timeout": 32_400}},
        "timeout": {"rollout": 28_800, "setup": 3_600},
    }
    one = copy.deepcopy(original)
    one.update({"num_tasks": 1, "max_concurrent": 1, "multiplex": 1})
    one["client"].update({"max_connections": 1, "max_keepalive_connections": 1})
    one["taskset"].update({"task_file": "/one", "task_file_sha256": "b" * 64})
    one["harness"]["runtime"]["session_timeout"] = 43_200
    one["timeout"]["rollout"] = 43_200

    assert recovery._normalized_recovery_config(original) == recovery._normalized_recovery_config(one)
    one["max_turns"] = 9
    assert recovery._normalized_recovery_config(original) != recovery._normalized_recovery_config(one)


def test_source_compatibility_binds_prime_revision_and_vmvm_execution() -> None:
    source = {
        "project_root": "/source",
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": "0" * 64,
        "verifiers_commit": "2" * 40,
        "verifiers_tree_sha256": "0" * 64,
        "renderers_commit": "3" * 40,
        "renderers_tree_sha256": "0" * 64,
        "vmvm_tb_v2_sha256": "4" * 64,
    }
    identity = {
        "source": source,
        "dataset": {"content_sha256": "5" * 64},
        "contract": {"model": "Kimi-K3"},
        "deployment": {
            key: value
            for key, value in {
                "id": "deployment",
                "endpoint": {},
                "serving_route_generation": {},
                "proxy_policy": {},
                "spec": {},
                "readiness_checkpoint": {},
                "routing": {},
            }.items()
        },
        "execution": {
            "rollout_concurrency": 2,
            "multiplex": 2,
            "http_max_connections": 2,
            "http_max_keepalive_connections": 2,
            "runtime": {"type": "vmvm", "session_timeout": 32_400, "tenant_id": "tenant"},
            "vmvm_environment": {
                "vacli_bin": "/vacli",
                "lease_start_concurrency": 2,
                "lease_retries": 20,
                "max_pull_retries": 20,
                "image_pull_timeout_sec": 3_600,
                "container_privileged": True,
            },
        },
    }
    recovered = copy.deepcopy(identity)
    recovered["execution"].update(
        {
            "rollout_concurrency": 1,
            "multiplex": 1,
            "http_max_connections": 1,
            "http_max_keepalive_connections": 1,
        }
    )
    recovered["execution"]["runtime"]["session_timeout"] = 43_200
    recovered["execution"]["vmvm_environment"]["lease_start_concurrency"] = 1
    assert recovery._source_compatible(identity, recovered)

    recovered["source"]["prime_rl_commit"] = "6" * 40
    assert not recovery._source_compatible(identity, recovered)
    recovered = copy.deepcopy(identity)
    recovered["execution"]["vmvm_environment"]["vacli_bin"] = "/other"
    assert not recovery._source_compatible(identity, recovered)


def test_materialized_one_task_config_passes_real_snapshot_and_approval(tmp_path: Path) -> None:
    workflow = Path(recovery.__file__).resolve().parent
    template = workflow / "configs/eval/tb4_kimi_k3_recovery12h.toml"
    task = tmp_path / "approved_task.txt"
    task.write_text("private-task-alpha\n")
    task_sha256 = hashlib.sha256(task.read_bytes()).hexdigest()
    config = tmp_path / "config.toml"
    config.write_bytes(recovery._materialize_recovery_config(template.read_bytes(), task.resolve(), task_sha256))

    records = snapshot(config, tmp_path / "inputs")
    observed_sha256, observed_count = validate_approval(
        tmp_path / "inputs",
        task,
        task_sha256,
    )

    assert observed_sha256 == task_sha256
    assert observed_count == 1
    assert records["task_file"]["source"] == str(task.resolve())
    parsed = tomllib.loads(config.read_text())
    assert parsed["num_tasks"] == 1
    assert parsed["taskset"]["task_file"] == str(task.resolve())
    assert parsed["taskset"]["task_file_sha256"] == task_sha256


def test_fresh_two_fallback_real_prelaunch_snapshot_and_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = Path(recovery.__file__).resolve().parents[3]
    project = tmp_path / "reviewed-project"
    project.mkdir()
    copied = set(recovery.RECOVERY_POLICY_REQUIRED_FILES) | {
        recovery.FRESH_TWO_CONFIG_RELATIVE.as_posix(),
        recovery.FRESH_TWO_TASK_RELATIVE.as_posix(),
    }
    for relative in sorted(copied):
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / relative, destination)
    vmvm_relative = Path("environments/vmvm_tb_v2/vmvm_tb_v2/_vacli/runtime.py")
    vmvm_path = project / vmvm_relative
    vmvm_path.parent.mkdir(parents=True, exist_ok=True)
    vmvm_path.write_text("RUNTIME_FIXTURE = True\n")
    for relative in (Path("deps/verifiers"), Path("deps/renderers")):
        dependency = project / relative
        dependency.mkdir(parents=True)
        (dependency / "source.py").write_text("SOURCE_FIXTURE = True\n")
        _commit_repository(dependency)
    expected_commit = _commit_repository(project)

    task = (project / recovery.FRESH_TWO_TASK_RELATIVE).resolve()
    config = (project / recovery.FRESH_TWO_CONFIG_RELATIVE).resolve()
    task_sha256 = hashlib.sha256(task.read_bytes()).hexdigest()
    config_sha256 = hashlib.sha256(config.read_bytes()).hexdigest()
    assert task_sha256 == recovery.FRESH_TWO_TASK_SHA256
    artifact_root = tmp_path / "route-inputs"
    artifact_root.mkdir()
    spec = _artifact(artifact_root / "spec.yaml", b"spec\n")
    readiness = _artifact(artifact_root / "readiness.json", b"{}\n")
    proxy = _artifact(artifact_root / "proxy.json", b"{}\n")
    output_dir = (tmp_path / "fresh-two-output").resolve()

    launch = recovery.validate_fresh_two_launch(
        output_dir,
        task,
        task_sha256,
        config,
        config_sha256,
        project_root=project,
        expected_prime_rl_commit=expected_commit,
        deployment_id="deployment",
        deployment_spec=spec.path,
        deployment_spec_sha256=spec.sha256,
        readiness_checkpoint=readiness.path,
        readiness_checkpoint_sha256=readiness.sha256,
        proxy_info=proxy.path,
        proxy_info_sha256=proxy.sha256,
        vacli_bin=recovery.REVIEWED_VACLI_BIN,
        vacli_max_concurrent_leases="2",
        vacli_lease_retries="20",
        vacli_max_pull_retries="20",
        vacli_image_pull_timeout_seconds="3600",
        vacli_container_privileged="1",
        environ={},
    )
    monkeypatch.chdir(project)
    records = snapshot(config, tmp_path / "fresh-two-inputs")
    observed_sha256, observed_count = validate_approval(
        tmp_path / "fresh-two-inputs",
        task,
        task_sha256,
    )

    assert launch["state"] == "launch_eligible"
    assert launch["mode"] == "fresh_two"
    assert launch["counts"] == {"tasks": 2, "expected_traces": 2}
    assert "deployment" not in json.dumps(launch)
    assert observed_sha256 == task_sha256
    assert observed_count == 2
    assert records["task_file"]["source"] == str(task)
    assert not output_dir.exists()

    with pytest.raises(recovery.SmokeRecoveryError, match="^fresh_two_state_forbidden$"):
        recovery.validate_fresh_two_launch(
            output_dir,
            task,
            task_sha256,
            config,
            config_sha256,
            project_root=project,
            expected_prime_rl_commit=expected_commit,
            deployment_id="deployment",
            deployment_spec=spec.path,
            deployment_spec_sha256=spec.sha256,
            readiness_checkpoint=readiness.path,
            readiness_checkpoint_sha256=readiness.sha256,
            proxy_info=proxy.path,
            proxy_info_sha256=proxy.sha256,
            vacli_bin=recovery.REVIEWED_VACLI_BIN,
            vacli_max_concurrent_leases="2",
            vacli_lease_retries="20",
            vacli_max_pull_retries="20",
            vacli_image_pull_timeout_seconds="3600",
            vacli_container_privileged="1",
            environ={"KIMI_SMOKE_RECOVERY_SELECTION": "/forbidden"},
        )


def test_recovery_wrapper_is_48h_fresh_only_and_reuses_guarded_launcher() -> None:
    wrapper = (Path(recovery.__file__).parent / "run_kimi_smoke_recovery.sbatch").read_text()

    assert "#SBATCH --time=2-00:00:00" in wrapper
    assert "${RESUME_DIR+x}" in wrapper
    assert '[[ -e "$output_dir" ]]' in wrapper
    assert 'bash "$workflow_dir/run_eval.sbatch"' in wrapper
    assert 'eval_config="$selection_dir/config.toml"' in wrapper
    assert "--expected-prime-rl-commit" in wrapper
    assert "--vacli-image-pull-timeout-seconds" in wrapper
    assert "tb4_kimi_k3_fresh_smoke12h.toml" in wrapper
    assert "verify-fresh-two" in wrapper
    assert "unset KIMI_SMOKE_RECOVERY_SELECTION" not in wrapper
    assert wrapper.index("${KIMI_SMOKE_RECOVERY_SELECTION+x}") < wrapper.index("verify-fresh-two")
    assert "SMOKE_REQUIRE_EXACT_PROVIDER_JSON=1" in wrapper
    assert "sbatch " not in wrapper
    assert "scancel " not in wrapper


def test_schema3_validator_binds_exact_target_and_self_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _artifact(tmp_path / "results.jsonl", _row(_trace("trace-a", "private-task-alpha")).raw)
    results.path.chmod(0o600)
    selection = _artifact(tmp_path / "selection.json", b"{}\n")
    source_smoke = _artifact(tmp_path / "source-smoke.json", b"{}\n")
    endpoint = {"authority_sha256": "a" * 64}
    generation = {"schema_version": 2, "coordinator": {}, "proxy": {}, "routes": []}
    policy = {"request_timeout": 43_200}
    readiness = {"path": "/readiness", "sha256": "b" * 64}
    body = {
        "schema_version": 3,
        "kind": recovery.COMPOSITE_KIND,
        "state": "passed",
        "ok": True,
        "deployment_id": "deployment",
        "deployment_spec_sha256": "c" * 64,
        "artifacts": {
            "results": results.record,
            "selection_attestation": selection.record,
            "recovery_smoke_checkpoint": source_smoke.record,
        },
    }
    payload = {**body, "smoke_checkpoint_sha256": hashlib.sha256(recovery.canonical_json(body)).hexdigest()}
    checkpoint = tmp_path / "smoke_checkpoint.json"
    checkpoint.write_text(json.dumps(payload, sort_keys=True) + "\n")
    checkpoint.chmod(0o444)
    recovery_identity = {
        "deployment": {
            "id": "deployment",
            "spec": {"sha256": "c" * 64},
            "readiness_checkpoint": readiness,
            "endpoint": endpoint,
            "serving_route_generation": generation,
            "proxy_policy": policy,
        }
    }
    monkeypatch.setattr(
        recovery,
        "_prepare_composite",
        lambda *_args, **_kwargs: (body, source_smoke, recovery_identity, {"tool_contract": {}}),
    )
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    evidence, observed_source, observed_generation = recovery.validate_composite_qualification(
        checkpoint,
        checkpoint_sha,
        deployment_id="deployment",
        deployment_spec_sha256="c" * 64,
        readiness_record=readiness,
        endpoint=endpoint,
        generation=generation,
        proxy_policy=policy,
    )
    assert evidence == {"tool_contract": {}}
    assert observed_source == source_smoke
    assert observed_generation == generation

    with pytest.raises(recovery.SmokeRecoveryError, match="^composite_target_mismatch$"):
        recovery.validate_composite_qualification(
            checkpoint,
            checkpoint_sha,
            deployment_id="other-deployment",
            deployment_spec_sha256="c" * 64,
            readiness_record=readiness,
            endpoint=endpoint,
            generation=generation,
            proxy_policy=policy,
        )


def test_smoke_qualification_dispatches_schema3_and_preserves_recovery_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _artifact(tmp_path / "spec.yaml", b"spec\n")
    readiness = _artifact(tmp_path / "readiness.json", b"{}\n")
    proxy = _artifact(tmp_path / "proxy.json", b"{}\n")
    checkpoint = _artifact(tmp_path / "composite.json", b'{"schema_version":3}\n')
    endpoint = {"authority_sha256": "a" * 64, "proxy_info": proxy.record}
    generation = {"schema_version": 2, "coordinator": {}, "proxy": {}, "routes": []}
    policy = {"request_timeout": 43_200}
    source = recovery.FileArtifact(tmp_path / "source.json", "b" * 64)
    evidence = {"tool_contract": {"schema_version": 1}}
    monkeypatch.setattr(
        qualification, "load_deployment_endpoint", lambda *_args, **_kwargs: SimpleNamespace(binding=endpoint)
    )
    monkeypatch.setattr(qualification, "validate_readiness", lambda *_args, **_kwargs: (generation, policy))
    calls: list[dict] = []

    def validate(*_args, **kwargs):
        calls.append(kwargs)
        return evidence, source, generation

    monkeypatch.setattr(recovery, "validate_composite_qualification", validate)

    result = qualification.validate_smoke_qualification(
        checkpoint.path,
        checkpoint.sha256,
        deployment_id="deployment",
        deployment_spec_path=spec.path,
        deployment_spec_sha256=spec.sha256,
        readiness_path=readiness.path,
        readiness_sha256=readiness.sha256,
        proxy_info_path=proxy.path,
        proxy_info_sha256=proxy.sha256,
        model="Kimi-K3",
    )

    assert result.schema_version == 3
    assert result.evaluator_evidence == evidence
    assert result.source_smoke.path == source.path
    assert result.source_generation == result.target_generation == generation
    assert calls[0]["deployment_id"] == "deployment"


def test_end_to_end_synthetic_selection_snapshot_combine_and_schema3_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = Path(recovery.__file__).resolve().parent
    original_tasks = tmp_path / "original-tasks.txt"
    original_tasks.write_bytes(b"private-task-alpha\nprivate-task-beta\n")
    original_task_sha = hashlib.sha256(original_tasks.read_bytes()).hexdigest()
    source_dir = tmp_path / "source-run"
    source_dir.mkdir(mode=0o700)
    (source_dir / ".writer.lock").touch()
    original_config_data = tomllib.loads((workflow / "configs/eval/tb4_kimi_k3_fresh_smoke12h.toml").read_text())
    original_config_data["taskset"]["task_file"] = str(original_tasks.resolve())
    original_config_data["taskset"]["task_file_sha256"] = original_task_sha
    original_config = source_dir / "config.toml"
    original_config.write_text(tomli_w.dumps(original_config_data))

    spec = tmp_path / "spec.yaml"
    readiness = tmp_path / "readiness.json"
    proxy = tmp_path / "proxy.json"
    spec.write_text("spec\n")
    readiness.write_text("{}\n")
    proxy.write_text("{}\n")
    spec_record = {"path": str(spec.resolve()), "sha256": hashlib.sha256(spec.read_bytes()).hexdigest()}
    readiness_record = {
        "path": str(readiness.resolve()),
        "sha256": hashlib.sha256(readiness.read_bytes()).hexdigest(),
    }
    proxy_record = {"path": str(proxy.resolve()), "sha256": hashlib.sha256(proxy.read_bytes()).hexdigest()}
    endpoint = {"proxy_info": proxy_record, "authority_sha256": "a" * 64}
    generation = {"schema_version": 2, "coordinator": {}, "proxy": {}, "routes": []}
    proxy_policy = {"request_timeout": 43_200}
    deployment = {
        "id": "deployment",
        "endpoint": endpoint,
        "serving_route_generation": generation,
        "proxy_policy": proxy_policy,
        "routing": {"deployment_id": "deployment", "headers": {"X-Deployment-Id": "deployment"}},
        "spec": spec_record,
        "readiness_checkpoint": readiness_record,
    }
    source_record = {
        "project_root": str((tmp_path / "project").resolve()),
        "prime_rl_commit": "1" * 40,
        "prime_rl_tree_sha256": hashlib.sha256(b"").hexdigest(),
        "verifiers_commit": "2" * 40,
        "verifiers_tree_sha256": hashlib.sha256(b"").hexdigest(),
        "renderers_commit": "3" * 40,
        "renderers_tree_sha256": hashlib.sha256(b"").hexdigest(),
        "vmvm_tb_v2_sha256": "4" * 64,
    }
    Path(source_record["project_root"]).mkdir()
    contract = {"model": "Kimi-K3", "context_tokens": 262_144}
    vmvm_environment = {
        "vacli_bin": "/vacli",
        "lease_start_concurrency": 2,
        "lease_retries": 20,
        "max_pull_retries": 20,
        "image_pull_timeout_sec": 3_600,
        "container_privileged": True,
    }
    source_identity = {
        "role": "smoke",
        "source": source_record,
        "config": {"resolved": _artifact(source_dir / "config-copy.toml", original_config.read_bytes()).record},
        "inputs": {"task_file": {"path": str(original_tasks.resolve()), "sha256": original_task_sha, "count": 2}},
        "dataset": {"kind": "archive", "content_sha256": "5" * 64},
        "deployment": deployment,
        "contract": contract,
        "execution": {
            "rollout_concurrency": 2,
            "multiplex": 2,
            "http_max_connections": 2,
            "http_max_keepalive_connections": 2,
            "runtime": original_config_data["harness"]["runtime"],
            "vmvm_environment": vmvm_environment,
        },
    }
    retained_row = _row(_trace("trace-retained", "private-task-beta"))
    source_results = _artifact(source_dir / "results.jsonl", retained_row.raw)
    source = {
        "run_dir": source_dir.resolve(),
        "identity": source_identity,
        "identity_sha256": "6" * 64,
        "identity_artifact": _artifact(source_dir / "eval_run_identity.json", b"{}\n"),
        "results_artifact": source_results,
        "receipt_artifact": _artifact(source_dir / "route_guard_success.json", b"{}\n"),
        "invocations_artifact": _artifact(source_dir / "eval_invocations.jsonl", b"{}\n"),
        "rows": [retained_row],
    }
    policy = {
        "schema_version": 1,
        "project_root": source_record["project_root"],
        "prime_rl_commit": source_record["prime_rl_commit"],
        "files": {"policy.py": "7" * 64},
        "closure_sha256": "8" * 64,
        "source_dependencies": {
            key: source_record[key]
            for key in (
                "prime_rl_tree_sha256",
                "verifiers_commit",
                "verifiers_tree_sha256",
                "renderers_commit",
                "renderers_tree_sha256",
                "vmvm_tb_v2_sha256",
            )
        },
    }
    monkeypatch.setattr(recovery, "_load_run", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(recovery, "_recovery_source_binding", lambda *_args, **_kwargs: policy)
    template = workflow / "configs/eval/tb4_kimi_k3_recovery12h.toml"
    selection_dir = tmp_path / "selection"
    recovery.create_selection(
        source_dir,
        original_tasks,
        original_task_sha,
        template,
        hashlib.sha256(template.read_bytes()).hexdigest(),
        Path(source_record["project_root"]),
        selection_dir,
        identity_loader=lambda *_args, **_kwargs: {},
        environ={},
    )
    selection_text = (selection_dir / "selection.json").read_text()
    assert "private-task-alpha" not in selection_text
    assert "private-task-beta" not in selection_text
    assert "trace-retained" not in selection_text

    selected_task = selection_dir / "approved_task.txt"
    selected_config = selection_dir / "config.toml"
    selected_task_sha = hashlib.sha256(selected_task.read_bytes()).hexdigest()
    selected_config_sha = hashlib.sha256(selected_config.read_bytes()).hexdigest()
    recovery_run = selection_dir / "run"
    launch = recovery.validate_recovery_launch(
        selection_dir / "selection.json",
        recovery_run,
        selected_task,
        selected_task_sha,
        selected_config,
        selected_config_sha,
        project_root=Path(source_record["project_root"]),
        expected_prime_rl_commit=source_record["prime_rl_commit"],
        deployment_id=deployment["id"],
        deployment_spec=spec,
        deployment_spec_sha256=spec_record["sha256"],
        readiness_checkpoint=readiness,
        readiness_checkpoint_sha256=readiness_record["sha256"],
        proxy_info=proxy,
        proxy_info_sha256=proxy_record["sha256"],
        vacli_bin="/vacli",
        vacli_max_concurrent_leases="1",
        vacli_lease_retries="20",
        vacli_max_pull_retries="20",
        vacli_image_pull_timeout_seconds="3600",
        vacli_container_privileged="1",
        identity_loader=lambda *_args, **_kwargs: {},
        environ={},
    )
    assert launch["state"] == "launch_eligible"
    snapshot(selected_config, recovery_run / "inputs")
    assert validate_approval(recovery_run / "inputs", selected_task, selected_task_sha) == (selected_task_sha, 1)

    recovered_row = _row(_trace("trace-recovered", "private-task-alpha"))
    recovery_results = _artifact(recovery_run / "results.jsonl", recovered_row.raw)
    selected_config_data = tomllib.loads(selected_config.read_text())
    recovery_identity = copy.deepcopy(source_identity)
    recovery_identity["config"]["resolved"] = recovery.FileArtifact(
        selected_config.resolve(), selected_config_sha
    ).record
    recovery_identity["inputs"]["task_file"] = {
        "path": str((recovery_run / "inputs/task_file.txt").resolve()),
        "sha256": selected_task_sha,
        "count": 1,
    }
    recovery_identity["execution"].update(
        {
            "rollout_concurrency": 1,
            "multiplex": 1,
            "http_max_connections": 1,
            "http_max_keepalive_connections": 1,
            "runtime": selected_config_data["harness"]["runtime"],
            "vmvm_environment": {**vmvm_environment, "lease_start_concurrency": 1},
        }
    )
    recovery_identity_file = _artifact(recovery_run / "eval_run_identity.json", b"{}\n")
    recovery_invocations = _artifact(recovery_run / "eval_invocations.jsonl", b"{}\n")
    recovery_receipt = _artifact(recovery_run / "route_guard_success.json", b"{}\n")
    recovery_checkpoint_path = recovery_run / "smoke_checkpoint.json"
    recovery_checkpoint_path.write_text("{}\n")
    recovery_checkpoint_path.chmod(0o444)
    recovery_checkpoint = recovery.FileArtifact(
        recovery_checkpoint_path.resolve(), hashlib.sha256(recovery_checkpoint_path.read_bytes()).hexdigest()
    )
    recovery_payload = {
        "eval_run_identity_sha256": "9" * 64,
        "artifacts": {
            "results": recovery_results.record,
            "eval_run_identity": recovery_identity_file.record,
            "eval_invocations": recovery_invocations.record,
            "route_guard_success": recovery_receipt.record,
        },
    }
    evidence = {"tool_contract": {"schema_version": 1}}
    monkeypatch.setattr(
        recovery,
        "_load_recovery_checkpoint",
        lambda *_args, **_kwargs: (
            recovery_checkpoint,
            recovery_payload,
            recovery_identity,
            evidence,
        ),
    )
    composite_dir = tmp_path / "composite"
    checkpoint_payload = recovery.create_composite(
        selection_dir / "selection.json",
        recovery_checkpoint_path,
        composite_dir,
        identity_loader=lambda *_args, **_kwargs: {},
    )
    checkpoint_path = composite_dir / "smoke_checkpoint.json"
    observed_evidence, observed_source, _ = recovery.validate_composite_qualification(
        checkpoint_path,
        hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        deployment_id=deployment["id"],
        deployment_spec_sha256=spec_record["sha256"],
        readiness_record=readiness_record,
        endpoint=endpoint,
        generation=generation,
        proxy_policy=proxy_policy,
        identity_loader=lambda *_args, **_kwargs: {},
    )

    assert checkpoint_payload["counts"]["traces"] == 2
    assert checkpoint_payload["ordering"] == [
        {"manifest_index": 0, "source": "recovery"},
        {"manifest_index": 1, "source": "original"},
    ]
    assert observed_evidence == evidence
    assert observed_source == recovery_checkpoint
    certificate_text = checkpoint_path.read_text()
    assert "private-task-alpha" not in certificate_text
    assert "private-task-beta" not in certificate_text
    assert "trace-retained" not in certificate_text
    assert "trace-recovered" not in certificate_text
