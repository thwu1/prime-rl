from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import sandoq_source_continuation as continuation
from direct_qwen_union_contract import UnionContractError
from materialize_qwen_provider_union import Partition


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _private_file(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    path.chmod(0o600)
    return path


def _source_lineage() -> dict:
    return {
        "routing": continuation.EPOCH3_ROUTING,
        "job_finality": {"all_terminal": True, "referenced_job_count": 2},
        "artifacts": {
            name: {"sha256": digest, "size_bytes": index + 1}
            for index, (name, digest) in enumerate(sorted(continuation.EPOCH3_ARTIFACTS.items()))
        },
        "transition_artifacts": {
            name: {"sha256": digest, "size_bytes": index + 1}
            for index, (name, digest) in enumerate(sorted(continuation.EPOCH_TRANSITION_ARTIFACTS.items()))
        },
    }


def _materialization_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    members = tuple(f"opaque-{index:04d}" for index in range(continuation.CONTINUATION_COUNT))
    retained = tuple(f"retained-{index:04d}" for index in range(continuation.SANDOQ_RETAINED_COUNT))
    compose = ("compose-row",)
    task_body = "".join(f"{member}\n" for member in members).encode()
    task_sha = _sha(task_body)
    monkeypatch.setattr(continuation, "CONTINUATION_TASK_SHA256", task_sha)
    selection_root = _private_dir(tmp_path / "selection")
    selection = _private_file(selection_root / "repair_manifest.json", b"selection\n")
    _private_file(selection_root / "repair_tasks.txt", task_body)
    provider_root = _private_dir(tmp_path / "provider")
    provider_receipt = _private_file(provider_root / "receipt.json", b"receipt\n")
    provider_task = _private_file(provider_root / "sandoq.tasks", task_body)
    project_root = _private_dir(tmp_path / "project")
    source = _private_file(project_root / "canonical.txt", b"source\n")
    template = _private_file(project_root / "template.toml", b"template\n")
    image_manifest = _private_file(project_root / "image-manifest.json", b"image\n")
    monkeypatch.setattr(continuation, "CURRENT_IMAGE_MANIFEST_SIZE", len(image_manifest.read_bytes()))
    dataset = _private_dir(tmp_path / "dataset")
    source_run = _private_dir(tmp_path / "source-run")
    _private_file(source_run / ".writer.lock", b"")
    _private_file(source_run / ".direct_router.lock", b"")
    private_root = tmp_path / "private"
    task_output = private_root / "source_continuation.tasks"
    config_output = private_root / "source_continuation.toml"
    receipt_output = private_root / "source_continuation_receipt.json"
    plan_output = private_root / "source_continuation_plan.json"
    config_body = b"resolved-config\n"
    code = {
        "base_revision": continuation.BASE_REVISION,
        "repository_revision": "a" * 40,
        "repository_tree": "b" * 40,
        "files": {name: "c" * 64 for name in continuation.CODE_FILES},
    }
    source_artifacts = _source_lineage()["artifacts"]
    selection_value = {
        "trace_contracts": {"repair": {}, "source": {}},
        "source": {
            "artifacts": {
                "config": source_artifacts["config.toml"],
                "direct_workers": source_artifacts["direct_workers.json"],
                "image_manifest": source_artifacts["inputs/image_manifest.json"],
                "inputs_manifest": source_artifacts["inputs/manifest.json"],
                "provenance": source_artifacts["provenance.txt"],
                "results": source_artifacts["results.jsonl"],
                "source_config": source_artifacts["inputs/source_config.toml"],
                "task_file": source_artifacts["inputs/task_file.txt"],
            }
        },
    }
    provider_value = {
        "partition": {
            "disjoint": True,
            "exhaustive": True,
            "sandoq_count": continuation.CONTINUATION_COUNT,
            "total_count": continuation.CONTINUATION_COUNT,
            "vmvm_count": 0,
        }
    }
    monkeypatch.setattr(continuation, "CANONICAL_SOURCE_SHA256", _sha(source.read_bytes()))
    monkeypatch.setattr(continuation, "_selection_value", lambda _body: selection_value)
    monkeypatch.setattr(continuation, "_provider_receipt_value", lambda _body: provider_value)
    monkeypatch.setattr(
        continuation,
        "_validate_source_run",
        lambda _path, **_kwargs: _source_lineage(),
    )
    monkeypatch.setattr(
        continuation,
        "_canonical_paths",
        lambda *_args: (source, dataset, template, source.read_bytes(), template.read_bytes()),
    )
    monkeypatch.setattr(
        continuation,
        "_canonical_image_manifest",
        lambda _body: (image_manifest, image_manifest.read_bytes()),
    )
    monkeypatch.setattr(
        continuation,
        "derive_partition",
        lambda *_args: Partition(members + retained, compose, continuation.CANONICAL_SOURCE_COUNT),
    )
    monkeypatch.setattr(continuation, "materialize_sandoq_config", lambda *_args, **_kwargs: config_body)
    monkeypatch.setattr(continuation, "_validate_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(continuation, "_code_binding", lambda: code)
    monkeypatch.setattr(continuation, "verify_canonical_dataset", lambda path: path)
    return {
        "members": members,
        "task_body": task_body,
        "task_sha": task_sha,
        "config_body": config_body,
        "code": code,
        "materialize": {
            "epoch3_source_run": source_run,
            "selection_manifest": selection,
            "provider_receipt": provider_receipt,
            "provider_task_file": provider_task,
            "canonical_source": source,
            "canonical_dataset": dataset,
            "canonical_template": template,
            "private_root": private_root,
            "task_output": task_output,
            "config_output": config_output,
            "receipt_output": receipt_output,
            "plan_output": plan_output,
        },
    }


def test_materialize_and_validate_plan_are_private_and_aggregate_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)

    summary = continuation.materialize(**fixture["materialize"])
    paths = fixture["materialize"]
    validated = continuation.validate_plan(
        plan=paths["plan_output"],
        plan_sha256=summary["plan_sha256"],
        task_file=paths["task_output"],
        task_file_sha256=fixture["task_sha"],
        config=paths["config_output"],
    )

    assert summary["task_count"] == continuation.CONTINUATION_COUNT
    assert validated.task_body == fixture["task_body"]
    assert validated.config_body == fixture["config_body"]
    for name in ("task_output", "config_output", "receipt_output", "plan_output"):
        metadata = paths[name].stat()
        assert stat_mode(metadata.st_mode) == 0o600
        assert metadata.st_nlink == 1
        assert metadata.st_uid == os.getuid()
    assert stat_mode(paths["private_root"].stat().st_mode) == 0o700
    public_evidence = paths["receipt_output"].read_text() + paths["plan_output"].read_text()
    assert not any(member in public_evidence for member in fixture["members"])
    assert validated.value["materialization"]["partition"]["sandoq_retained_count"] == 1_266
    assert validated.value["materialization"]["partition"]["retained_zero_reward_nonexported_count"] == 517
    selection_lineage = validated.value["materialization"]["lineage"]["selection"]
    assert selection_lineage["continuation_trace_contract"] == {
        "id": "qwen3-a95b-direct-medium",
        "sha256": "c83833ac8950a17a1d9e7a65ac1fe8f585376a838e4737ce92b20c8eaa4ab777",
    }


def test_materialize_requires_a_fresh_private_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    fixture["materialize"]["private_root"].mkdir(mode=0o700)

    with pytest.raises(continuation.SourceContinuationError, match="private_root_invalid"):
        continuation.materialize(**fixture["materialize"])


def test_materialize_rejects_private_root_inside_an_input_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    root = fixture["materialize"]["selection_manifest"].parent / "continuation-output"
    fixture["materialize"].update(
        private_root=root,
        task_output=root / "source_continuation.tasks",
        config_output=root / "source_continuation.toml",
        receipt_output=root / "source_continuation_receipt.json",
        plan_output=root / "source_continuation_plan.json",
    )

    with pytest.raises(continuation.SourceContinuationError, match="private_root_invalid"):
        continuation.materialize(**fixture["materialize"])


def test_materialize_rejects_private_root_inside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    root = Path(continuation.__file__).resolve().parents[3] / (
        f".source-continuation-test-{tmp_path.name}"
    )
    fixture["materialize"].update(
        private_root=root,
        task_output=root / "source_continuation.tasks",
        config_output=root / "source_continuation.toml",
        receipt_output=root / "source_continuation_receipt.json",
        plan_output=root / "source_continuation_plan.json",
    )

    with pytest.raises(continuation.SourceContinuationError, match="private_root_invalid"):
        continuation.materialize(**fixture["materialize"])
    assert not root.exists()


def test_old_max_selection_contract_cannot_be_claimed_as_continuation_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    continuation.materialize(**fixture["materialize"])
    receipt = json.loads(fixture["materialize"]["receipt_output"].read_bytes())
    contradictory = copy.deepcopy(receipt)
    selection = contradictory["lineage"]["selection"]
    selection["selection_trace_contracts"]["repair"] = {
        "id": "qwen3-a95b",
        "sha256": "338772c5840f201851c30a29df1f3986af414b1fa22c325aff5783cb8b460a84",
    }
    selection["continuation_trace_contract"] = selection["selection_trace_contracts"]["repair"]

    with pytest.raises(
        continuation.SourceContinuationError,
        match="materialization_receipt_invalid",
    ):
        continuation._validate_receipt(contradictory)


def stat_mode(mode: int) -> int:
    return mode & 0o777


@pytest.mark.parametrize("target", ["selection", "provider_receipt", "provider_task", "source"])
def test_validate_plan_reauthenticates_every_recorded_private_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    summary = continuation.materialize(**fixture["materialize"])
    paths = fixture["materialize"]
    calls = {"source": 0}
    original_selection = continuation._selection_value
    original_provider = continuation._provider_receipt_value

    def source_check(_path: Path, **_kwargs) -> dict:
        calls["source"] += 1
        if target == "source":
            raise continuation.SourceContinuationError("epoch3_source_artifact_invalid")
        return _source_lineage()

    if target == "selection":
        monkeypatch.setattr(
            continuation,
            "_selection_value",
            lambda _body: (_ for _ in ()).throw(continuation.SourceContinuationError("selection_manifest_invalid")),
        )
    else:
        monkeypatch.setattr(continuation, "_selection_value", original_selection)
    if target == "provider_receipt":
        monkeypatch.setattr(
            continuation,
            "_provider_receipt_value",
            lambda _body: (_ for _ in ()).throw(continuation.SourceContinuationError("provider_receipt_invalid")),
        )
    else:
        monkeypatch.setattr(continuation, "_provider_receipt_value", original_provider)
    if target == "provider_task":
        paths["provider_task_file"].write_bytes(b"opaque-tamper\n")
        paths["provider_task_file"].chmod(0o600)
    monkeypatch.setattr(continuation, "_validate_source_run", source_check)

    with pytest.raises(continuation.SourceContinuationError):
        continuation.validate_plan(
            plan=paths["plan_output"],
            plan_sha256=summary["plan_sha256"],
            task_file=paths["task_output"],
            task_file_sha256=fixture["task_sha"],
            config=paths["config_output"],
        )
    if target == "source":
        assert calls["source"] == 1


def test_materialize_rejects_wrong_provider_subset_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    members = fixture["members"]
    monkeypatch.setattr(
        continuation,
        "derive_partition",
        lambda *_args: Partition(
            members[:-1] + tuple(f"retained-{index:04d}" for index in range(continuation.SANDOQ_RETAINED_COUNT + 1)),
            (members[-1],),
            continuation.CANONICAL_SOURCE_COUNT,
        ),
    )

    with pytest.raises(
        continuation.SourceContinuationError,
        match="canonical_partition_invalid",
    ):
        continuation.materialize(**fixture["materialize"])

    assert not fixture["materialize"]["private_root"].exists()


def _certify_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    plan_root = _private_dir(tmp_path / "plan-root")
    task = _private_file(plan_root / "tasks", b"opaque-task\n")
    monkeypatch.setattr(continuation, "CONTINUATION_TASK_SHA256", _sha(task.read_bytes()))
    config = _private_file(plan_root / "config", b"config\n")
    plan = plan_root / "plan.json"
    plan_value = {
        "outputs": {
            "task_file": {"path": str(task)},
            "config": {"path": str(config)},
        }
    }
    plan_body = continuation._json(plan_value)
    _private_file(plan, plan_body)
    plan_sha = _sha(plan_body)
    source_run = _private_dir(tmp_path / "source-run")
    _private_file(source_run / ".writer.lock", b"")
    _private_file(source_run / ".direct_router.lock", b"")
    lineage = {"epoch3_source": _source_lineage()}
    validated = continuation.ValidatedPlan(
        value={
            "inputs": {"epoch3_source_run": str(source_run)},
            "materialization": {"lineage": lineage},
            "code": {"repository_revision": "a" * 40},
        },
        sha256=plan_sha,
        private_root=plan_root,
        task_file=task,
        task_body=task.read_bytes(),
        config=config,
        config_body=config.read_bytes(),
        receipt=plan_root / "receipt",
        dataset=tmp_path,
    )
    run = _private_dir(tmp_path / "run")
    inputs = _private_dir(run / "inputs")
    for name in ("manifest.json", "source_config.toml", "task_file.txt", "image_manifest.json"):
        _private_file(inputs / name, f"{name}\n".encode())
    for name, body in (
        (".writer.lock", b""),
        ("eval_run_identity.json", b"identity\n"),
        ("direct_workers.json", b"workers\n"),
        ("results.jsonl", b"result\n"),
        ("sandoq_cleanup_audit.json", b"{}\n"),
        ("config.toml", b"config\n"),
        ("provenance.txt", b"provenance\n"),
    ):
        _private_file(run / name, body)
    envelope = {
        "eval_run_identity_sha256": "d" * 64,
        "identity": {
            "source": {},
            "deployment": {"worker_manifest": {"sha256": _sha((run / "direct_workers.json").read_bytes())}},
        },
    }
    shared = {"contract": {}, "deployment": {"worker_count": 24}}
    execution = {
        "cleanup_must_succeed": True,
        "rollout_concurrency": 64,
        "multiplex": 64,
        "http_max_connections": 32,
        "http_max_keepalive_connections": 32,
        "sandoq_environment": {
            "environment": "oci-runner",
            "task_network": "public",
            "pool_size": 64,
            "pool_min_size": 0,
            "tunnel_policy": "host-interception-no-tunnel",
        },
        "runtime": {
            "type": "sandoq",
            "mode": "oci-runner",
            "network_access": True,
            "host_tunnel": "none",
            "expected_environment": "oci-runner",
        },
    }
    traces = {
        "traces": continuation.CONTINUATION_COUNT,
        "tasks": continuation.CONTINUATION_COUNT,
        "sampled_tokens": 1,
        "model_io_turns": continuation.CONTINUATION_COUNT,
        "provider_reported_zero_reasoning_tool_turns": 0,
        "provider_explicit_empty_reasoning_tool_turns": 0,
    }
    cleanup = {
        "audit_sha256": _sha((run / "sandoq_cleanup_audit.json").read_bytes()),
        "assignment_attempts": continuation.CONTINUATION_COUNT,
        "failures": 0,
        "zero_drop": True,
    }
    monkeypatch.setattr(continuation, "validate_plan", lambda **_kwargs: validated)
    monkeypatch.setattr(
        continuation,
        "_validate_run_identity",
        lambda **_kwargs: (envelope, shared, execution),
    )
    monkeypatch.setattr(
        continuation,
        "_audit_results_anchored",
        lambda *_args: (_sha((run / "results.jsonl").read_bytes()), traces),
    )
    monkeypatch.setattr(continuation, "validate_cleanup", lambda *_args, **_kwargs: (cleanup, {}))
    monkeypatch.setattr(continuation, "_provider_source", lambda _identity: {"source": "sealed"})
    source_calls = []

    def validate_source(path: Path, **_kwargs) -> dict:
        source_calls.append(path)
        return _source_lineage()

    monkeypatch.setattr(continuation, "_validate_source_run", validate_source)
    return {
        "validated": validated,
        "source_calls": source_calls,
        "args": {
            "plan": plan,
            "plan_sha256": plan_sha,
            "run": run,
            "cleanup_audit": run / "sandoq_cleanup_audit.json",
            "identity_output": run / "source_continuation_identity.json",
            "output": run / "qwen_sandoq_source_continuation_certificate.json",
        },
    }


def test_certify_emits_private_merge_evidence_and_reaudits_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _certify_fixture(tmp_path, monkeypatch)

    result = continuation.certify(**fixture["args"])

    assert result["state"] == "passed"
    assert fixture["source_calls"] == [Path(fixture["validated"].value["inputs"]["epoch3_source_run"])]
    certificate = json.loads(fixture["args"]["output"].read_bytes())
    assert certificate["task_count"] == continuation.CONTINUATION_COUNT
    assert certificate["merge_contract"]["canonical_count"] == continuation.SANDOQ_COUNT
    assert certificate["merge_contract"]["retained_count"] == continuation.SANDOQ_RETAINED_COUNT
    assert certificate["trace_audit"]["traces"] == continuation.CONTINUATION_COUNT
    assert certificate["trace_audit"]["contract"] == continuation.CONTINUATION_TRACE_CONTRACT
    assert certificate["trace_audit"]["error_traces"] == 0
    assert certificate["trace_audit"]["sequence_length_violations"] == 0
    assert certificate["pool_cleanup"]["all_assignments_verified"] is True
    for name in ("identity_output", "output"):
        metadata = fixture["args"][name].stat()
        assert stat_mode(metadata.st_mode) == 0o600
        assert metadata.st_nlink == 1


@pytest.mark.parametrize("failure", ["duplicate", "missing", "invalid", "cleanup"])
def test_certify_rejects_invalid_or_incomplete_evidence_without_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    fixture = _certify_fixture(tmp_path, monkeypatch)
    if failure == "invalid":
        monkeypatch.setattr(
            continuation,
            "_audit_results_anchored",
            lambda *_args: (
                "f" * 64,
                {"traces": 1_232, "tasks": 1_232, "model_io_turns": 1_232},
            ),
        )
    elif failure == "cleanup":
        monkeypatch.setattr(
            continuation,
            "validate_cleanup",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("private detail")),
        )
    else:
        monkeypatch.setattr(
            continuation,
            "_audit_results_anchored",
            lambda *_args: (_ for _ in ()).throw(UnionContractError("trace_audit_failed")),
        )

    with pytest.raises(continuation.SourceContinuationError, match="continuation_evidence_invalid"):
        continuation.certify(**fixture["args"])

    assert not fixture["args"]["identity_output"].exists()
    assert not fixture["args"]["output"].exists()


def test_anchored_audit_uses_plan_bound_task_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _private_dir(tmp_path / "run")
    inputs = _private_dir(run / "inputs")
    _private_file(inputs / "task_file.txt", b"alternate\n")
    _private_file(run / "results.jsonl", b"{}\n")
    planned = b"planned\n"
    monkeypatch.setattr(continuation, "CONTINUATION_COUNT", 1)
    monkeypatch.setattr(continuation, "CONTINUATION_TASK_SHA256", _sha(planned))

    def summarize(traces, *, expected_slugs, **_kwargs):
        assert expected_slugs == {"planned"}
        assert list(traces) == [{}]
        return (
            {
                "traces": 1,
                "tasks": 1,
                "sampled_tokens": 0,
                "model_io_turns": 1,
                "provider_reported_zero_reasoning_tool_turns": 0,
                "provider_explicit_empty_reasoning_tool_turns": 0,
            },
            False,
        )

    monkeypatch.setattr(continuation, "_summarize_traces", summarize)
    with continuation.PrivateDirectory.open(run, "run_invalid") as root:
        digest, summary = continuation._audit_results_anchored(root, planned)

    assert digest == _sha(b"{}\n")
    assert summary["tasks"] == 1


def test_cli_validate_plan_stdout_is_aggregate_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opaque = "private-opaque-member"
    plan = tmp_path / "plan"
    task = tmp_path / "task"
    config = tmp_path / "config"
    monkeypatch.setattr(
        continuation,
        "validate_plan",
        lambda **_kwargs: SimpleNamespace(sha256="a" * 64),
    )

    assert (
        continuation.main(
            [
                "validate-plan",
                "--plan",
                str(plan),
                "--plan-sha256",
                "a" * 64,
                "--task-file",
                str(task),
                "--task-file-sha256",
                "b" * 64,
                "--config",
                str(config),
            ]
        )
        == 0
    )
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == {
        "plan_sha256": "a" * 64,
        "state": "valid",
        "task_count": continuation.CONTINUATION_COUNT,
    }
    assert opaque not in stdout


def test_private_input_permissions_are_enforced(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "private")
    artifact = root / "artifact"
    artifact.write_text("opaque-private-value\n")
    artifact.chmod(0o644)

    with pytest.raises(continuation.SourceContinuationError):
        continuation._private_read(artifact, "private_input_invalid")


def test_canonical_image_manifest_drift_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _private_file(tmp_path / "images.json", b"sealed-image-manifest\n")
    monkeypatch.setattr(continuation, "CURRENT_IMAGE_MANIFEST_SHA256", _sha(image.read_bytes()))
    monkeypatch.setattr(continuation, "CURRENT_IMAGE_MANIFEST_SIZE", len(image.read_bytes()))
    template = (
        f'[taskset]\nimage_manifest = "{image}"\nimage_manifest_sha256 = "{_sha(image.read_bytes())}"\n'
    ).encode()

    assert continuation._canonical_image_manifest(template) == (image, image.read_bytes())
    image.write_bytes(b"drifted-image-manifest\n")
    image.chmod(0o600)

    with pytest.raises(
        continuation.SourceContinuationError,
        match="canonical_image_manifest_invalid",
    ):
        continuation._canonical_image_manifest(template)


def test_source_finality_checks_every_referenced_job_and_rejects_nonterminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import migrate_qwen_router_affinity as migration

    source = _private_dir(tmp_path / "source")
    _private_file(
        source / "provenance.txt",
        b"slurm_job_id=123\nresume_slurm_job_id=456\n",
    )
    observed: list[str] = []

    def terminal(job_id: str) -> bool:
        observed.append(job_id)
        return job_id != "123"

    monkeypatch.setattr(migration, "slurm_job_is_terminal", terminal)
    with continuation.PrivateDirectory.open(source, "source_invalid") as root:
        with pytest.raises(
            continuation.SourceContinuationError,
            match="epoch3_source_job_not_terminal",
        ):
            continuation._source_jobs_finality(root)

    assert observed == ["123", "456"]


def test_source_finality_emits_only_aggregate_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import migrate_qwen_router_affinity as migration

    source = _private_dir(tmp_path / "source")
    _private_file(
        source / "provenance.txt",
        b"slurm_job_id=123\nresume_slurm_job_id=456\n",
    )
    monkeypatch.setattr(migration, "slurm_job_is_terminal", lambda _job_id: True)

    with continuation.PrivateDirectory.open(source, "source_invalid") as root:
        finality = continuation._source_jobs_finality(root)

    assert finality == {"all_terminal": True, "referenced_job_count": 2}
    assert "123" not in json.dumps(finality)
    assert "456" not in json.dumps(finality)


def test_publisher_rolls_back_target_on_immediate_post_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = _private_dir(tmp_path / "private")
    target = private / "artifact"
    original_stat = continuation.os.stat
    injected = False

    def failing_stat(path, *args, **kwargs):
        nonlocal injected
        if path == target.name and kwargs.get("dir_fd") is not None and not injected:
            injected = True
            raise OSError("injected post-link failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(continuation.os, "stat", failing_stat)
    with continuation.PrivateDirectory.open(private, "private_invalid") as root:
        with pytest.raises(continuation.SourceContinuationError, match="publish_failed"):
            root.publish([(target, b"private\n")], "publish_failed")

    assert injected
    assert not target.exists()
    assert not tuple(private.glob(".artifact.tmp.*"))


@pytest.mark.parametrize("anchor", ["private", "source"])
def test_materialize_rolls_back_all_outputs_on_post_publish_anchor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anchor: str,
) -> None:
    fixture = _materialization_fixture(tmp_path, monkeypatch)
    private = fixture["materialize"]["private_root"]
    selected = private if anchor == "private" else fixture["materialize"]["epoch3_source_run"]
    moved = tmp_path / f"{anchor}-moved"
    original_publish = continuation.PrivateDirectory.publish

    def swapping_publish(self, outputs, code):
        publication = original_publish(self, outputs, code)
        if self.path == private:
            selected.rename(moved)
            _private_dir(selected)
        return publication

    monkeypatch.setattr(continuation.PrivateDirectory, "publish", swapping_publish)

    with pytest.raises(continuation.SourceContinuationError):
        continuation.materialize(**fixture["materialize"])

    for root in (private, moved if anchor == "private" else private):
        assert not (root / "source_continuation.tasks").exists()
        assert not (root / "source_continuation.toml").exists()
        assert not (root / "source_continuation_receipt.json").exists()
        assert not (root / "source_continuation_plan.json").exists()


@pytest.mark.parametrize("anchor", ["run", "source", "plan"])
def test_certify_rolls_back_outputs_on_post_publish_anchor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anchor: str,
) -> None:
    fixture = _certify_fixture(tmp_path, monkeypatch)
    run = fixture["args"]["run"]
    selected = {
        "run": run,
        "source": Path(fixture["validated"].value["inputs"]["epoch3_source_run"]),
        "plan": fixture["args"]["plan"].parent,
    }[anchor]
    moved = tmp_path / f"{anchor}-moved"
    original_publish = continuation.PrivateDirectory.publish

    def swapping_publish(self, outputs, code):
        publication = original_publish(self, outputs, code)
        if self.path == run:
            selected.rename(moved)
            _private_dir(selected)
        return publication

    monkeypatch.setattr(continuation.PrivateDirectory, "publish", swapping_publish)

    with pytest.raises(continuation.SourceContinuationError):
        continuation.certify(**fixture["args"])

    for root in (run, moved if anchor == "run" else run):
        assert not (root / "source_continuation_identity.json").exists()
        assert not (root / "qwen_sandoq_source_continuation_certificate.json").exists()


@pytest.mark.parametrize(
    "artifact",
    [
        "results.jsonl",
        "eval_run_identity.json",
        "direct_workers.json",
        "sandoq_cleanup_audit.json",
    ],
)
def test_certify_rejects_run_evidence_mutation_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    fixture = _certify_fixture(tmp_path, monkeypatch)
    run = fixture["args"]["run"]
    traces = {
        "traces": continuation.CONTINUATION_COUNT,
        "tasks": continuation.CONTINUATION_COUNT,
        "sampled_tokens": 1,
        "model_io_turns": continuation.CONTINUATION_COUNT,
        "provider_reported_zero_reasoning_tool_turns": 0,
        "provider_explicit_empty_reasoning_tool_turns": 0,
    }

    def mutate_results(*_args):
        original = _sha((run / "results.jsonl").read_bytes())
        (run / artifact).write_bytes(b"mutated\n")
        (run / artifact).chmod(0o600)
        return original, traces

    monkeypatch.setattr(continuation, "_audit_results_anchored", mutate_results)

    with pytest.raises(
        continuation.SourceContinuationError,
        match="source_changed_during_certification",
    ):
        continuation.certify(**fixture["args"])

    assert not fixture["args"]["identity_output"].exists()
    assert not fixture["args"]["output"].exists()
