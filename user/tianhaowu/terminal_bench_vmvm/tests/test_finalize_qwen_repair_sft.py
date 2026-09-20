from __future__ import annotations

import hashlib
import json
from pathlib import Path

import direct_qwen_workers as direct
import finalize_qwen_repair_sft as finalizer
import pytest
from audit_traces import QWEN3_A95B_MODEL_IO_CONTRACT_ID, qwen_repair_trace_contracts_value


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _artifact(path: Path) -> dict[str, int | str]:
    body = path.read_bytes()
    return {"bytes": len(body), "sha256": _sha256(body)}


def _write_layout(tmp_path: Path, *, expected_count: int = 2) -> tuple[finalizer.RepairFinalizeOptions, bytes]:
    project = tmp_path / "project" / "source"
    project.mkdir(parents=True)
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    (workflow / "configs" / "eval").mkdir(parents=True)
    materializer_body = b"synthetic-materializer\n"
    template_body = b"synthetic-template\n"
    exporter_body = b"synthetic-exporter\n"
    (workflow / "materialize_qwen_repair.py").write_bytes(materializer_body)
    (workflow / "configs" / "eval" / "mobius_qwen_a95b_2500.toml").write_bytes(template_body)
    (workflow / "export_sft.py").write_bytes(exporter_body)
    source_root = tmp_path / "evals" / "runs"
    source = source_root / "repair"
    (source / "inputs").mkdir(parents=True)
    output_root = tmp_path / "sft" / "outputs"
    output_root.mkdir(parents=True)
    for lock in (".direct_router.lock", ".writer.lock"):
        (source / lock).touch()
    task_body = b"opaque-a\nopaque-b\n"
    task_sha256 = _sha256(task_body)
    source_config = b"synthetic-repair-config\n"
    provenance = b"synthetic-provenance\n"
    files = {
        "config.toml": b"synthetic-resolved-config\n",
        "inputs/manifest.json": b"{}\n",
        "inputs/source_config.toml": source_config,
        "inputs/task_file.txt": task_body,
        "inputs/image_manifest.json": b"{}\n",
        "provenance.txt": provenance,
        "results.jsonl": b"synthetic-results\n",
        "direct_workers.json": b"{}\n",
    }
    for relative, body in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    approved_count = expected_count + 1
    approved_task_sha256 = "9" * 64
    selection_source_artifacts = {
        name: {"sha256": approved_task_sha256 if name == "task_file" else "8" * 64, "size_bytes": 1}
        for name in finalizer.SELECTION_SOURCE_ARTIFACTS
    }
    selection = {
        "approval": {
            "approved_task_count": approved_count,
            "approved_task_file_sha256": approved_task_sha256,
        },
        "code": {
            "exporter_sha256": _sha256(exporter_body),
            "materializer_sha256": _sha256(materializer_body),
            "repository_revision": "a" * 40,
            "submodules": {
                "deps/pydantic-config": "c" * 40,
                "deps/renderers": "d" * 40,
                "deps/verifiers": "e" * 40,
            },
        },
        "config": {
            "capture_model_io": True,
            "enable_thinking": True,
            "max_concurrent": direct.MAX_DIRECT_CONCURRENCY,
            "max_total_tokens": 262_144,
            "preserve_thinking": True,
            "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
            "reasoning_effort": "max",
            "retry_class_count": len(direct.ROLLOUT_RETRY_POLICY),
            "retry_policy_sha256": _sha256(
                "".join(f"{name}\n" for name in sorted(direct.ROLLOUT_RETRY_POLICY)).encode()
            ),
            "sha256": _sha256(source_config),
            "template_sha256": _sha256(template_body),
        },
        "kind": "qwen-aggregate-repair-selection",
        "planner": {
            "approved_task_count": approved_count,
            "contract_verifiers_revision": direct.ADMISSION_VERIFIERS_REVISION,
            "missing_or_errored_count": expected_count,
            "module_sha256": direct.ADMISSION_RESUME_MODULE_SHA256,
            "retained_count": 1,
            "task_index_order_sha256": "7" * 64,
        },
        "schema_version": 3,
        "selection": {
            "approved_repair_count": expected_count,
            "missing_or_errored_count": expected_count,
            "missing_or_errored_indices_sha256": "1" * 64,
            "missing_or_errored_task_file_sha256": task_sha256,
            "repair_union_indices_sha256": "2" * 64,
            "strict_invalid_pass_count": 0,
            "strict_invalid_pass_indices_sha256": _sha256(b""),
            "strict_invalid_pass_task_file_sha256": _sha256(b""),
            "task_file_sha256": task_sha256,
        },
        "source": {
            "artifacts": selection_source_artifacts,
            "routing_epoch": 3,
            "task_count": approved_count,
        },
        "source_partition": {
            "error_traces": expected_count - 1,
            "exhaustive": True,
            "invalid_positive_traces": 0,
            "positive_reward_traces": 0,
            "repair_tasks": expected_count,
            "retained_original_tasks": 1,
            "retained_valid_positive_traces": 0,
            "reward_zero_traces": 1,
            "seen_traces": 2,
            "source_task_count": approved_count,
            "superseded_legacy_empty_reasoning_traces": 0,
            "unseen_tasks": 1,
        },
        "trace_contracts": qwen_repair_trace_contracts_value(),
    }
    selection_body = json.dumps(selection, indent=2, sort_keys=True).encode() + b"\n"
    selection_path = tmp_path / "repair" / "repair_manifest.json"
    selection_path.parent.mkdir()
    selection_path.write_bytes(selection_body)
    selection_path.chmod(0o600)
    for filename, body in (
        ("repair_tasks.txt", task_body),
        ("repair_missing_or_errored_tasks.txt", task_body),
        ("repair_strict_invalid_pass_tasks.txt", b""),
    ):
        selected = selection_path.parent / filename
        selected.write_bytes(body)
        selected.chmod(0o600)
    options = finalizer.RepairFinalizeOptions(
        project_dir=project,
        expected_project_revision="a" * 40,
        source_root=source_root,
        source_dir=source,
        expected_provenance_sha256=_sha256(provenance),
        repair_selection_manifest=selection_path,
        expected_repair_selection_manifest_sha256=_sha256(selection_body),
        output_root=output_root,
        output_dir=output_root / "repair-corpus",
        expected_count=expected_count,
        validation_permyriad=500,
        split_salt="repair-split-v1",
    )
    return options, selection_body


def _audit(source: Path, options: finalizer.RepairFinalizeOptions) -> dict:
    task_sha256 = _artifact(source / "inputs/task_file.txt")["sha256"]
    return {
        "artifacts": finalizer._source_artifacts(source),
        "routing": {
            "routing_epoch": 1,
            "manifest_schema_version": 3,
            "provider_concurrency": 32,
            "queue_size": 32,
            "router_policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
        },
        "corpus": {
            "task_count": options.expected_count,
            "task_file_sha256": task_sha256,
            "taskset_id": "terminal-bench-vmvm",
            "dataset_revision": "b" * 40,
        },
    }


def _write_export(output: Path, source: Path, project: Path, expected_count: int) -> dict:
    (output / "train").mkdir(parents=True)
    (output / "validation").mkdir()
    train = b"{}\n{}\n"
    validation = b""
    split = b"{}\n"
    (output / "train" / "train.jsonl").write_bytes(train)
    (output / "validation" / "train.jsonl").write_bytes(validation)
    (output / "task-split.json").write_bytes(split)
    target_contract = (
        json.dumps(finalizer.exporter.TARGET_RENDERING_CONTRACT, indent=2, sort_keys=True).encode() + b"\n"
    )
    assert _sha256(target_contract) == finalizer.exporter.TARGET_RENDERING_CONTRACT_SHA256
    (output / finalizer.exporter.TARGET_RENDERING_CONTRACT_FILENAME).write_bytes(target_contract)
    (output / finalizer.exporter.TARGET_RENDERING_CONTRACT_FILENAME).chmod(0o600)
    manifest = {
        "artifacts": {
            "task-split.json": {"bytes": len(split), "sha256": _sha256(split)},
            finalizer.exporter.TARGET_RENDERING_CONTRACT_FILENAME: {
                "bytes": len(target_contract),
                "sha256": _sha256(target_contract),
            },
            "train/train.jsonl": {"bytes": len(train), "sha256": _sha256(train)},
            "validation/train.jsonl": {"bytes": len(validation), "sha256": _sha256(validation)},
        },
        "config": {
            "capture_model_io": True,
            "dataset_revision": "b" * 40,
            "max_input_tokens": 262_144,
            "max_output_tokens": 262_144,
            "max_total_tokens": 262_144,
            "model": direct.EXPECTED_MODEL,
            "num_rollouts": 1,
            "taskset_id": "terminal-bench-vmvm",
        },
        "counts": {
            "approved_tasks": expected_count,
            "emitted_rows": 2,
            "excluded_error_traces": 1,
            "input_traces": expected_count,
            "scored_pass_traces": 1,
            "selected_pass_traces": 1,
            "selected_traces": 1,
            "train_rows": 2,
            "train_traces": 1,
        },
        "exporter": {
            "file_sha256": _artifact(project / "user" / "tianhaowu" / "terminal_bench_vmvm" / "export_sft.py")[
                "sha256"
            ],
            "format_version": 3,
        },
        "format": {
            "assistant_finish_reason": "retained verbatim for every sampled assistant message",
            "assistant_tool_calls": "OpenAI function-call objects",
            "history_assistant_reasoning": "retained verbatim",
            "loss_mask": "message.trainable; exactly one final assistant message is true",
            "sample_unit": "one unique sampled assistant node with its root-to-node context",
            "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
            "task_identity": "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)",
        },
        "max_sequence_tokens": 262_144,
        "selection": "pass-only",
        "source_validation": {
            "max_sequence_tokens": 262_144,
            "model_io_contract": QWEN3_A95B_MODEL_IO_CONTRACT_ID,
            "require_exact_provider_json": False,
            "require_model_io": True,
            "require_reasoning": True,
            "require_request_graph_match": True,
        },
        "source_artifacts": {
            relative: _artifact(source / relative)
            for relative in (
                "config.toml",
                "provenance.txt",
                "inputs/manifest.json",
                "inputs/source_config.toml",
                "inputs/task_file.txt",
                "inputs/image_manifest.json",
                "results.jsonl",
            )
        },
        "split": {
            "policy": "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000",
            "split_salt": "repair-split-v1",
            "validation_permyriad": 500,
        },
        "target_rendering": finalizer.exporter.TARGET_RENDERING_CONTRACT,
    }
    manifest_body = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    (output / "manifest.json").write_bytes(manifest_body)
    return {
        "approved_tasks": expected_count,
        "excluded_error_traces": 1,
        "input_traces": expected_count,
        "output_sha256": {
            "manifest": _sha256(manifest_body),
            "target_rendering_contract": _sha256(target_contract),
            "train": _sha256(train),
            "validation": _sha256(validation),
        },
        "rows": {"total": 2, "train": 2, "validation": 0},
        "selected_traces": expected_count - 1,
        "selection": "pass-only",
        "status": "exported",
    }


def test_finalize_publishes_exact_fresh_repair_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, selection_body = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")
    repository_checks: list[int] = []

    def validate_repository(path: Path, revision: str) -> Path:
        assert path == options.project_dir
        assert revision == options.expected_project_revision
        repository_checks.append(1)
        return path

    def audit_source(source: Path, *_args: object) -> dict:
        return _audit(source, options)

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        assert code == "sft_export_failed"
        assert "--routing-epoch-index" not in command
        assert command.count("--require-task-index-binding") == 1
        output = Path(command[command.index("--output-dir") + 1])
        return _write_export(output, options.source_dir, options.project_dir, options.expected_count)

    summary = finalizer.finalize_qwen_repair_sft(
        options,
        repository_validator=validate_repository,
        source_auditor=audit_source,
        command_runner=run_command,
        submodule_reader=lambda _project, _revision: {
            "deps/pydantic-config": "c" * 40,
            "deps/renderers": "d" * 40,
            "deps/verifiers": "e" * 40,
        },
        runtime_validator=lambda project: project / "user" / "tianhaowu" / "terminal_bench_vmvm",
    )

    assert len(repository_checks) == 3
    assert summary["status"] == "finalized"
    assert summary["input_traces"] == options.expected_count
    assert (options.output_dir / finalizer.SELECTION_COPY_FILENAME).read_bytes() == selection_body
    attestation = json.loads((options.output_dir / finalizer.ATTESTATION_FILENAME).read_bytes())
    assert set(attestation) == {
        "kind",
        "schema_version",
        "repair_selection_manifest_sha256",
        "source_artifacts",
        "routing",
        "selection",
        "corpus",
        "code",
    }
    assert attestation["kind"] == "qwen-direct-repair-attestation"
    assert attestation["schema_version"] == finalizer.ATTESTATION_SCHEMA_VERSION
    assert attestation["routing"]["routing_epoch"] == 1
    assert attestation["routing"]["manifest_schema_version"] == 3
    assert attestation["routing"]["provider_concurrency"] == 32
    assert attestation["routing"]["router_policy"] == "consistent_hash"
    assert attestation["routing"]["request_id_headers"] == ["x-session-id"]
    assert attestation["selection"] == {
        "missing_or_errored_count": options.expected_count,
        "strict_invalid_pass_count": 0,
        "union_count": options.expected_count,
        "union_indices_sha256": "2" * 64,
        "union_task_file_sha256": _sha256((options.source_dir / "inputs/task_file.txt").read_bytes()),
    }
    for copy_name, source_name in finalizer.SELECTION_SOURCE_FILENAMES.items():
        assert (options.output_dir / copy_name).read_bytes() == (
            options.repair_selection_manifest.parent / source_name
        ).read_bytes()
    assert set(attestation["source_artifacts"]) == set(finalizer.SOURCE_ARTIFACTS)
    manifest = json.loads((options.output_dir / "manifest.json").read_bytes())
    assert manifest["source_validation"] == {
        "max_sequence_tokens": 262_144,
        "model_io_contract": QWEN3_A95B_MODEL_IO_CONTRACT_ID,
        "require_exact_provider_json": False,
        "require_model_io": True,
        "require_reasoning": True,
        "require_request_graph_match": True,
    }
    assert manifest["source_artifacts"]["results.jsonl"] == attestation["source_artifacts"]["results.jsonl"]
    assert manifest["source_artifacts"]["direct_workers.json"] == attestation["source_artifacts"]["direct_workers.json"]
    assert set(manifest["artifacts"]) == {
        "task-split.json",
        finalizer.exporter.TARGET_RENDERING_CONTRACT_FILENAME,
        "train/train.jsonl",
        "validation/train.jsonl",
    }


def test_sandoq_repair_uses_named_provider_transition_without_routing_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _selection_body = _write_layout(tmp_path)
    (options.source_dir / "config.toml").write_text('[harness.runtime]\ntype = "sandoq"\n')
    (options.source_dir / "eval_run_identity.json").write_text("{}\n")
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")
    provider = {
        "eval_run_identity_sha256": "1" * 64,
        "identity_compatibility_sha256": "2" * 64,
        "sandbox_provider": "sandoq",
        "transition_kind": finalizer.VMVM_TO_SANDOQ_TRANSITION_KIND,
    }

    def audit_source(source: Path, *_args: object) -> dict:
        return {
            "artifacts": finalizer._source_artifacts(
                source,
                sandbox_provider="sandoq",
            ),
            "corpus": {
                "task_count": options.expected_count,
                "task_file_sha256": _artifact(source / "inputs/task_file.txt")["sha256"],
                "taskset_id": "terminal-bench-vmvm",
                "dataset_revision": "b" * 40,
            },
            "provider": provider,
        }

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        assert code == "sft_export_failed"
        assert "--routing-epoch-index" not in command
        output = Path(command[command.index("--output-dir") + 1])
        (output / "train").mkdir(parents=True)
        (output / "validation").mkdir()
        (output / "manifest.json").write_text("{}\n")
        return {
            "approved_tasks": options.expected_count,
            "eval_run_identity_sha256": provider["eval_run_identity_sha256"],
            "excluded_error_traces": 1,
            "input_traces": options.expected_count,
            "output_sha256": {},
            "rows": {"total": 1, "train": 1, "validation": 0},
            "sandbox_provider": "sandoq",
            "selected_traces": 1,
            "selection": "pass-only",
            "status": "exported",
        }

    def validate_export(
        summary: dict,
        _output: Path,
        _expected_count: int,
        source_artifacts: dict,
        _corpus: dict,
        _validation_permyriad: int,
        _split_salt: str,
        _exporter_sha256: str,
        observed_provider: dict,
    ) -> tuple[dict, dict]:
        assert observed_provider == provider
        return {"source_artifacts": dict(source_artifacts)}, {"manifest.json": _artifact(_output / "manifest.json")}

    monkeypatch.setattr(finalizer, "_validate_export_summary", validate_export)
    monkeypatch.setattr(
        finalizer.migration,
        "_publish_directory",
        lambda staged, output, _validator: staged.rename(output),
    )
    summary = finalizer.finalize_qwen_repair_sft(
        options,
        repository_validator=lambda path, _revision: path,
        source_auditor=audit_source,
        command_runner=run_command,
        submodule_reader=lambda _project, _revision: {
            "deps/pydantic-config": "c" * 40,
            "deps/renderers": "d" * 40,
            "deps/verifiers": "e" * 40,
        },
        runtime_validator=lambda project: project / "user" / "tianhaowu" / "terminal_bench_vmvm",
    )

    attestation = json.loads((options.output_dir / finalizer.ATTESTATION_FILENAME).read_text())
    assert summary["sandbox_provider"] == "sandoq"
    assert attestation["kind"] == finalizer.SANDOQ_ATTESTATION_KIND
    assert attestation["schema_version"] == finalizer.SANDOQ_ATTESTATION_SCHEMA_VERSION
    assert "routing" not in attestation
    assert attestation["provider_transition"] == {
        "cleanup_implied_successful_traces": 1,
        "cleanup_must_succeed": True,
        "kind": finalizer.VMVM_TO_SANDOQ_TRANSITION_KIND,
        "repair_eval_run_identity_sha256": "1" * 64,
        "repair_identity_compatibility_sha256": "2" * 64,
        "repair_sandbox_provider": "sandoq",
        "schema_version": 1,
        "source_sandbox_provider": "vmvm",
    }


def test_late_repository_failure_leaves_no_canonical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _selection_body = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")
    calls = 0

    def validate_repository(path: Path, _revision: str) -> Path:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise finalizer.common.FinalizationError("project_revision_mismatch")
        return path

    def run_command(command: list[str], _cwd: Path, _code: str) -> dict:
        output = Path(command[command.index("--output-dir") + 1])
        return _write_export(output, options.source_dir, options.project_dir, options.expected_count)

    with pytest.raises(finalizer.RepairFinalizationError, match="^project_revision_mismatch$"):
        finalizer.finalize_qwen_repair_sft(
            options,
            repository_validator=validate_repository,
            source_auditor=lambda source, *_args: _audit(source, options),
            command_runner=run_command,
            submodule_reader=lambda _project, _revision: {
                "deps/pydantic-config": "c" * 40,
                "deps/renderers": "d" * 40,
                "deps/verifiers": "e" * 40,
            },
            runtime_validator=lambda project: project / "user" / "tianhaowu" / "terminal_bench_vmvm",
        )
    assert not options.output_dir.exists()


def test_source_audit_rejects_epoch_three_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _selection_body = _write_layout(tmp_path)
    task_body = (options.source_dir / "inputs/task_file.txt").read_bytes()
    task_file_sha256 = _sha256(task_body)
    include = ", ".join(json.dumps(value) for value in sorted(direct.ROLLOUT_RETRY_POLICY))
    config = f"""
num_tasks = {options.expected_count}
num_rollouts = 1
max_concurrent = {direct.MAX_DIRECT_CONCURRENCY}
multiplex = {direct.MAX_DIRECT_CONCURRENCY}
max_input_tokens = 262144
max_output_tokens = 262144
max_total_tokens = 262144

[client]
capture_model_io = true

[sampling]
max_tokens = 32768

[sampling.chat_template_kwargs]
enable_thinking = true
preserve_thinking = true

[retries.rollout]
max_retries = 2
include = [{include}]
exclude = []

[taskset]
id = "terminal-bench-vmvm"
dataset_revision = "{"b" * 40}"
task_file_sha256 = "{task_file_sha256}"
""".lstrip()
    (options.source_dir / "config.toml").write_text(config)
    (options.source_dir / "inputs" / "source_config.toml").write_text(config)
    selection = finalizer.RepairSelection(
        body=b"{}\n",
        sha256="f" * 64,
        selection_bodies={},
        selection_artifacts={},
        selection_paths={},
        config_sha256=_sha256(config.encode()),
        task_file_sha256=task_file_sha256,
        repair_union_indices_sha256="1" * 64,
        task_count=options.expected_count,
        missing_or_errored_count=options.expected_count,
        strict_invalid_pass_count=0,
        approved_task_count=options.expected_count,
        template_sha256="e" * 64,
        materializer_sha256="d" * 64,
        exporter_sha256="f" * 64,
        repository_revision="a" * 40,
        source_artifacts={},
        source_partition={},
        submodules={
            "deps/pydantic-config": "c" * 40,
            "deps/renderers": "d" * 40,
            "deps/verifiers": "e" * 40,
        },
        trace_contracts=qwen_repair_trace_contracts_value(),
    )
    monkeypatch.setattr(
        finalizer.direct,
        "audit_run_directory",
        lambda _source: {
            "ok": True,
            "routing_epoch": 3,
            "manifest_schema_version": 3,
            "provider_concurrency": 32,
            "queue_size": 32,
            "router_policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
        },
    )

    with pytest.raises(finalizer.RepairFinalizationError, match="^source_not_fresh_schema3_repair$"):
        finalizer._audit_source(
            options.source_dir,
            options.expected_count,
            options.expected_provenance_sha256,
            selection,
        )


def test_runtime_origin_is_bound_to_loaded_modules(tmp_path: Path) -> None:
    project = Path(finalizer.__file__).resolve().parents[3]
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"

    assert finalizer._validate_runtime_origin(project) == workflow
    with pytest.raises(finalizer.RepairFinalizationError, match="^runtime_origin_mismatch$"):
        finalizer._validate_runtime_origin(tmp_path)


def test_generation_repair_audit_requires_exact_current24_contract(tmp_path: Path) -> None:
    options, selection_body = _write_layout(tmp_path)
    selection = finalizer._load_repair_selection(
        options.repair_selection_manifest,
        _sha256(selection_body),
        options.expected_count,
    )
    contract = finalizer.generation._load_contract()
    artifacts = {
        name: {"bytes": 1, "sha256": "8" * 64}
        for name in (*finalizer.SOURCE_ARTIFACTS, *finalizer.GENERATION_SOURCE_ARTIFACTS)
    }
    artifacts["inputs/task_file.txt"]["sha256"] = selection.task_file_sha256
    artifacts[finalizer.generation.CAPACITY_SMOKE_FILENAME]["sha256"] = "7" * 64
    routing = {
        "capacity_smoke_sha256": "7" * 64,
        "endpoint_bundle_sha256": contract["target_generation"]["endpoint_bundle_sha256"],
        "manifest_schema_version": 3,
        "provider_concurrency": 48,
        "queue_size": 48,
        "request_id_headers": ["x-session-id"],
        "rollout_concurrency": 96,
        "router_policy": "consistent_hash",
        "routing_epoch": 1,
        "serving_generation": 2,
        "serving_generation_transition_sha256": "9" * 64,
        "spec_sha256": contract["target_generation"]["spec_sha256"],
        "worker_count": 24,
        "vmvm_lease_concurrency": 4,
    }
    audit = {
        "artifacts": artifacts,
        "routing": routing,
        "corpus": {
            "dataset_revision": "a" * 40,
            "task_count": options.expected_count,
            "task_file_sha256": selection.task_file_sha256,
            "taskset_id": "terminal-bench-vmvm",
        },
    }
    finalizer._validate_source_audit(audit, selection, options.expected_count)
    audit["routing"] = {**routing, "worker_count": 16}
    with pytest.raises(finalizer.RepairFinalizationError, match="^source_audit_invalid$"):
        finalizer._validate_source_audit(audit, selection, options.expected_count)


def test_selection_rejects_extra_metadata(tmp_path: Path) -> None:
    options, selection_body = _write_layout(tmp_path)
    selection = json.loads(selection_body)
    selection["task_identifiers"] = ["forbidden"]
    body = json.dumps(selection, indent=2, sort_keys=True).encode() + b"\n"
    options.repair_selection_manifest.write_bytes(body)

    with pytest.raises(finalizer.RepairFinalizationError, match="^repair_selection_invalid$"):
        finalizer._load_repair_selection(
            options.repair_selection_manifest,
            _sha256(body),
            options.expected_count,
        )


def test_selection_accepts_exact_mixed_category_union(tmp_path: Path) -> None:
    options, selection_body = _write_layout(tmp_path)
    selection = json.loads(selection_body)
    missing_body = b"opaque-a\n"
    strict_body = b"opaque-b\n"
    (options.repair_selection_manifest.parent / "repair_missing_or_errored_tasks.txt").write_bytes(missing_body)
    (options.repair_selection_manifest.parent / "repair_strict_invalid_pass_tasks.txt").write_bytes(strict_body)
    selection["planner"]["missing_or_errored_count"] = 1
    selection["planner"]["retained_count"] = 2
    selection["selection"]["missing_or_errored_count"] = 1
    selection["selection"]["missing_or_errored_task_file_sha256"] = _sha256(missing_body)
    selection["selection"]["strict_invalid_pass_count"] = 1
    selection["selection"]["strict_invalid_pass_task_file_sha256"] = _sha256(strict_body)
    selection["source_partition"] = {
        "error_traces": 0,
        "exhaustive": True,
        "invalid_positive_traces": 1,
        "positive_reward_traces": 1,
        "repair_tasks": 2,
        "retained_original_tasks": 1,
        "retained_valid_positive_traces": 0,
        "reward_zero_traces": 1,
        "seen_traces": 2,
        "source_task_count": 3,
        "superseded_legacy_empty_reasoning_traces": 0,
        "unseen_tasks": 1,
    }
    body = json.dumps(selection, indent=2, sort_keys=True).encode() + b"\n"
    options.repair_selection_manifest.write_bytes(body)

    loaded = finalizer._load_repair_selection(
        options.repair_selection_manifest,
        _sha256(body),
        options.expected_count,
    )

    assert loaded.missing_or_errored_count == 1
    assert loaded.strict_invalid_pass_count == 1
    assert loaded.task_count == 2


@pytest.mark.parametrize("mutation", ["missing", "extra", "public-mode"])
def test_selection_rejects_missing_extra_or_non_private_category_file(
    tmp_path: Path,
    mutation: str,
) -> None:
    options, selection_body = _write_layout(tmp_path)
    category = options.repair_selection_manifest.parent / "repair_missing_or_errored_tasks.txt"
    if mutation == "missing":
        category.unlink()
    elif mutation == "extra":
        category.write_bytes(category.read_bytes() + b"opaque-extra\n")
        category.chmod(0o600)
    else:
        category.chmod(0o644)

    with pytest.raises(
        finalizer.RepairFinalizationError,
        match="^repair_selection_(?:invalid|contract_mismatch)$",
    ):
        finalizer._load_repair_selection(
            options.repair_selection_manifest,
            _sha256(selection_body),
            options.expected_count,
        )


def test_selection_toctou_leaves_no_canonical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _selection_body = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")

    def run_command(command: list[str], _cwd: Path, _code: str) -> dict:
        output = Path(command[command.index("--output-dir") + 1])
        summary = _write_export(output, options.source_dir, options.project_dir, options.expected_count)
        category = options.repair_selection_manifest.parent / "repair_missing_or_errored_tasks.txt"
        category.write_bytes(category.read_bytes() + b"opaque-tamper\n")
        category.chmod(0o600)
        return summary

    with pytest.raises(finalizer.RepairFinalizationError, match="^repair_selection_changed$"):
        finalizer.finalize_qwen_repair_sft(
            options,
            repository_validator=lambda path, _revision: path,
            source_auditor=lambda source, *_args: _audit(source, options),
            command_runner=run_command,
            submodule_reader=lambda _project, _revision: {
                "deps/pydantic-config": "c" * 40,
                "deps/renderers": "d" * 40,
                "deps/verifiers": "e" * 40,
            },
            runtime_validator=lambda project: project / "user" / "tianhaowu" / "terminal_bench_vmvm",
        )
    assert not options.output_dir.exists()


def test_main_emits_only_stable_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(
        finalizer,
        "finalize_qwen_repair_sft",
        lambda _options: (_ for _ in ()).throw(finalizer.RepairFinalizationError("source_run_active")),
    )
    arguments = [
        "--project-dir",
        "/synthetic/project",
        "--expected-project-revision",
        "a" * 40,
        "--source-root",
        "/synthetic/evals",
        "--source-dir",
        "/synthetic/evals/repair",
        "--expected-provenance-sha256",
        "b" * 64,
        "--repair-selection-manifest",
        "/synthetic/repair/manifest.json",
        "--expected-repair-selection-manifest-sha256",
        "c" * 64,
        "--output-root",
        "/synthetic/sft",
        "--output-dir",
        "/synthetic/sft/repair",
        "--expected-count",
        "2",
        "--validation-permyriad",
        "500",
        "--split-salt",
        "repair-v1",
    ]

    assert finalizer.main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"code": "source_run_active", "status": "error"}
