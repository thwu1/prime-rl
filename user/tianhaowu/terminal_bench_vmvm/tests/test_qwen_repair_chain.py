from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import finalize_qwen_repair_sft as repair_finalizer
import pytest
import qwen_repair_chain as chain


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _write(path: Path, body: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(mode)


def _argument(command: chain.ChildCommand, name: str) -> Path:
    index = command.argv.index(name)
    return Path(command.argv[index + 1])


def _finalizer_summary(expected_count: int) -> dict[str, Any]:
    return {
        "approved_tasks": expected_count,
        "input_traces": expected_count,
        "rows": {"total": 3, "train": 2, "validation": 1},
        "selected_traces": 2,
        "selection": "pass-only",
        "status": "finalized",
    }


@dataclass
class FakeRunner:
    repair_count: int
    source: Path
    attestation: chain.ProjectAttestation
    mutate_source: bool = False
    mutate_selection: bool = False
    mutate_original_export_on_merge: bool = False
    mutate_repair_export_on_merge: bool = False
    stages: list[str] = field(default_factory=list)

    def __call__(self, command: chain.ChildCommand, _log_dir: Path) -> dict[str, Any] | None:
        self.stages.append(command.stage)
        if command.stage == "materialize":
            if self.mutate_source:
                (self.source / "results.jsonl").write_bytes(b"changed\n")
            if self.repair_count == 0:
                return {
                    "approved_repair_count": 0,
                    "approved_task_file_sha256": _sha256((self.source / "inputs" / "task_file.txt").read_bytes()),
                    "missing_or_errored_count": 0,
                    "ok": True,
                    "repair_union_indices_sha256": _sha256(b""),
                    "status": "nothing_to_repair",
                    "strict_invalid_pass_count": 0,
                    "task_index_order_sha256": "7" * 64,
                }
            output = _argument(command, "--output-dir")
            output.mkdir()
            task_body = b"".join(f"opaque-repair-{index:04d}\n".encode() for index in range(self.repair_count))
            task_sha256 = _sha256(task_body)
            task_file = output / "repair_tasks.txt"
            config_file = output / "repair_config.toml"
            manifest_file = output / "repair_manifest.json"
            missing_file = output / "repair_missing_or_errored_tasks.txt"
            strict_file = output / "repair_strict_invalid_pass_tasks.txt"
            config_body = f"""
model = "{direct.EXPECTED_MODEL}"
num_tasks = {self.repair_count}
num_rollouts = 1
max_concurrent = 64
multiplex = 64
max_input_tokens = 262144
max_output_tokens = 262144
max_total_tokens = 262144

[client]
capture_model_io = true
max_connections = 32
max_keepalive_connections = 32

[sampling]
max_tokens = 32768
chat_template_kwargs = {{ enable_thinking = true, preserve_thinking = true }}

[taskset]
task_file = {json.dumps(str(task_file))}
task_file_sha256 = "{task_sha256}"
""".lstrip().encode()
            config_sha256 = _sha256(config_body)
            source_task_sha256 = _sha256((self.source / "inputs" / "task_file.txt").read_bytes())
            manifest = {
                "approval": {
                    "approved_task_count": chain.EXPECTED_ORIGINAL_COUNT,
                    "approved_task_file_sha256": source_task_sha256,
                },
                "code": {
                    "exporter_sha256": self.attestation.exporter_sha256,
                    "materializer_sha256": self.attestation.materializer_sha256,
                    "repository_revision": self.attestation.revision,
                    "submodules": dict(self.attestation.submodules),
                },
                "config": {
                    "capture_model_io": True,
                    "enable_thinking": True,
                    "max_concurrent": direct.MAX_DIRECT_CONCURRENCY,
                    "max_total_tokens": chain.MAX_SEQUENCE_TOKENS,
                    "preserve_thinking": True,
                    "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
                    "retry_class_count": len(direct.ROLLOUT_RETRY_POLICY),
                    "retry_policy_sha256": _sha256(
                        "".join(f"{name}\n" for name in sorted(direct.ROLLOUT_RETRY_POLICY)).encode()
                    ),
                    "sha256": config_sha256,
                    "template_sha256": self.attestation.repair_template_sha256,
                },
                "kind": "qwen-aggregate-repair-selection",
                "planner": {
                    "approved_task_count": chain.EXPECTED_ORIGINAL_COUNT,
                    "contract_verifiers_revision": direct.ADMISSION_VERIFIERS_REVISION,
                    "missing_or_errored_count": self.repair_count,
                    "module_sha256": direct.ADMISSION_RESUME_MODULE_SHA256,
                    "retained_count": chain.EXPECTED_ORIGINAL_COUNT - self.repair_count,
                    "task_index_order_sha256": "7" * 64,
                },
                "schema_version": 2,
                "selection": {
                    "approved_repair_count": self.repair_count,
                    "missing_or_errored_count": self.repair_count,
                    "missing_or_errored_indices_sha256": "4" * 64,
                    "missing_or_errored_task_file_sha256": task_sha256,
                    "repair_union_indices_sha256": "5" * 64,
                    "strict_invalid_pass_count": 0,
                    "strict_invalid_pass_indices_sha256": _sha256(b""),
                    "strict_invalid_pass_task_file_sha256": _sha256(b""),
                    "task_file_sha256": task_sha256,
                },
                "source": {
                    "artifacts": {
                        name: {
                            "sha256": source_task_sha256 if name == "task_file" else "8" * 64,
                            "size_bytes": 1,
                        }
                        for name in repair_finalizer.SELECTION_SOURCE_ARTIFACTS
                    },
                    "routing_epoch": 3,
                    "task_count": chain.EXPECTED_ORIGINAL_COUNT,
                },
            }
            manifest_body = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
            for path, body in (
                (task_file, task_body),
                (missing_file, task_body),
                (strict_file, b""),
                (config_file, config_body),
                (manifest_file, manifest_body),
            ):
                _write(path, body)
            return {
                "approved_repair_count": self.repair_count,
                "config_sha256": config_sha256,
                "manifest_sha256": _sha256(manifest_body),
                "missing_or_errored_count": self.repair_count,
                "ok": True,
                "repair_union_indices_sha256": "5" * 64,
                "status": "materialized",
                "strict_invalid_pass_count": 0,
                "task_file_sha256": task_sha256,
                "task_index_order_sha256": "7" * 64,
            }
        if command.stage == "repair_eval":
            assert command.argv[0] == "/bin/bash"
            assert command.environment["VACLI_MAX_CONCURRENT_LEASES"] == "2"
            assert command.environment["OPENAI_API_KEY"] == "EMPTY"
            repair_dir = Path(command.environment["OUTPUT_DIR"])
            if self.mutate_selection:
                selection_file = Path(command.environment["DIRECT_QWEN_APPROVED_TASK_FILE"])
                selection_file.write_bytes(selection_file.read_bytes() + b"opaque-tamper\n")
            repair_dir.mkdir()
            _write(repair_dir / "provenance.txt", b"repair-provenance\n")
            _write(repair_dir / "results.jsonl", b"repair-results\n")
            return None
        if command.stage == "finalize_original":
            has_exclusion = "--exclusion-selection-manifest" in command.argv
            assert has_exclusion is (self.repair_count > 0)
            output = _argument(command, "--output-dir")
            output.mkdir()
            artifacts = {
                "manifest": (output / "manifest.json", b"original-manifest\n"),
                "routing_epoch_index": (output / chain.common.INDEX_FILENAME, b"index\n"),
                "train": (output / "train" / "train.jsonl", b"train\n"),
                "validation": (output / "validation" / "train.jsonl", b"validation\n"),
            }
            for path, body in artifacts.values():
                _write(path, body)
            summary = _finalizer_summary(chain.EXPECTED_ORIGINAL_COUNT)
            if self.repair_count:
                summary["exclusion"] = {
                    "excluded_present_traces": self.repair_count,
                    "missing_tasks": 0,
                    "missing_or_errored_count": self.repair_count,
                    "selection_manifest_sha256": _sha256(
                        _argument(command, "--exclusion-selection-manifest").read_bytes()
                    ),
                    "strict_invalid_pass_count": 0,
                    "union_count": self.repair_count,
                }
            summary["output_sha256"] = {name: _sha256(body) for name, (_path, body) in artifacts.items()}
            return summary
        if command.stage == "finalize_repair":
            output = _argument(command, "--output-dir")
            output.mkdir()
            attestation_body = b"repair-attestation\n"
            manifest_body = b"repair-manifest\n"
            selection_manifest = _argument(command, "--repair-selection-manifest")
            _write(output / repair_finalizer.ATTESTATION_FILENAME, attestation_body)
            for copy_name, source_name in repair_finalizer.SELECTION_SOURCE_FILENAMES.items():
                _write(output / copy_name, (selection_manifest.parent / source_name).read_bytes())
            _write(output / "manifest.json", manifest_body)
            summary = _finalizer_summary(self.repair_count)
            summary["attestation_sha256"] = _sha256(attestation_body)
            summary["manifest_sha256"] = _sha256(manifest_body)
            return summary
        if command.stage == "merge":
            original_export = _argument(command, "--original-export-dir")
            repair_export = _argument(command, "--repair-export-dir")
            assert str(_argument(command, "--original-export-manifest-sha256")) == _sha256(
                (original_export / "manifest.json").read_bytes()
            )
            assert str(_argument(command, "--repair-export-manifest-sha256")) == _sha256(
                (repair_export / "manifest.json").read_bytes()
            )
            assert str(_argument(command, "--original-export-tree-sha256")) == chain.merger._export_tree_sha256(
                original_export,
                "test_original_export_invalid",
            )
            assert str(_argument(command, "--repair-export-tree-sha256")) == chain.merger._export_tree_sha256(
                repair_export,
                "test_repair_export_invalid",
            )
            if self.mutate_original_export_on_merge:
                _write(original_export / "late-extra", b"late mutation\n")
                return None
            if self.mutate_repair_export_on_merge:
                _write(repair_export / "late-extra", b"late mutation\n")
                return None
            output = _argument(command, "--output-dir")
            output.mkdir()
            manifest_body = b"merged-manifest\n"
            _write(output / "manifest.json", manifest_body)
            artifacts = {
                "task_split": (output / "task-split.json", b"task-split\n"),
                "train": (output / "train" / "train.jsonl", b"merged-train\n"),
                "validation": (output / "validation" / "train.jsonl", b"merged-validation\n"),
            }
            for path, body in artifacts.values():
                _write(path, body)
            return {
                "manifest_sha256": _sha256(manifest_body),
                "ok": True,
                "output_sha256": {name: _sha256(body) for name, (_path, body) in artifacts.items()},
                "rows": {"total": 6, "train": 4, "validation": 2},
                "tasks": {"total": 4, "train": 3, "validation": 1},
            }
        raise AssertionError("unexpected stage")


def _layout(tmp_path: Path) -> tuple[chain.RepairChainOptions, chain.ProjectAttestation, dict[Path, bytes]]:
    source_root = tmp_path / "sources" / "evals"
    source = source_root / "original"
    inputs = source / "inputs"
    inputs.mkdir(parents=True)
    task_body = b"".join(f"opaque-approved-{index:04d}\n".encode() for index in range(chain.EXPECTED_ORIGINAL_COUNT))
    config = f"""
num_tasks = {chain.EXPECTED_ORIGINAL_COUNT}
num_rollouts = 1
max_concurrent = 64
multiplex = 64
max_input_tokens = 262144
max_output_tokens = 262144
max_total_tokens = 262144

[client]
capture_model_io = true
max_connections = 32
max_keepalive_connections = 32

[sampling]
max_tokens = 32768
chat_template_kwargs = {{ enable_thinking = true, preserve_thinking = true }}
""".lstrip().encode()
    files = {
        ".direct_router.lock": b"",
        ".writer.lock": b"",
        "config.toml": config,
        "direct_workers.json": b"{}\n",
        "inputs/manifest.json": b"{}\n",
        "inputs/source_config.toml": config,
        "inputs/task_file.txt": task_body,
        "provenance.txt": b"slurm_job_id=123\n",
        "results.jsonl": b"synthetic-results\n",
    }
    for relative, body in files.items():
        _write(source / relative, body)
    runtime_root = tmp_path / "private" / "runtime"
    output_root = tmp_path / "private" / "outputs"
    runtime_root.mkdir(parents=True)
    output_root.mkdir(parents=True)
    project = Path(chain.__file__).resolve().parents[3]
    options = chain.RepairChainOptions(
        project_dir=project,
        expected_project_revision="a" * 40,
        source_root=source_root,
        source_dir=source,
        approved_task_file_sha256=_sha256(task_body),
        expected_provenance_sha256=_sha256(files["provenance.txt"]),
        runtime_root=runtime_root,
        runtime_dir=runtime_root / "attempt",
        output_root=output_root,
        original_export_dir=output_root / "original",
        repair_export_dir=output_root / "repair",
        merged_output_dir=output_root / "merged",
        validation_permyriad=500,
        split_salt="opaque-qwen-chain-v1",
    )
    attestation = chain.ProjectAttestation(
        revision=options.expected_project_revision,
        submodules={name: "c" * 40 for name in chain.common.REQUIRED_RUNTIME_SUBMODULES},
        materializer_sha256="b" * 64,
        exporter_sha256="e" * 64,
        repair_template_sha256="6" * 64,
    )
    source_bytes = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    return options, attestation, source_bytes


def test_repair_chain_success(tmp_path: Path) -> None:
    options, attestation, source_bytes = _layout(tmp_path)
    runner = FakeRunner(2, options.source_dir, attestation)

    summary = chain.run_repair_chain(
        options,
        runner=runner,
        project_validator=lambda _project, _revision: attestation,
        environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
    )

    assert summary["status"] == "merged"
    assert summary["repair_count"] == 2
    assert runner.stages == [
        "materialize",
        "repair_eval",
        "finalize_original",
        "finalize_repair",
        "merge",
    ]
    assert summary["merged"]["tasks"]["total"] == 4
    assert stat.S_IMODE((options.runtime_dir / "chain_summary.json").stat().st_mode) == 0o600
    assert {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    } == source_bytes


def test_repair_chain_preserves_recoverable_partial_tail_through_merge(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    results = options.source_dir / "results.jsonl"
    results.write_bytes(results.read_bytes() + b'{"task":{"idx":2499')
    source_bytes = {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    }
    runner = FakeRunner(2, options.source_dir, attestation)

    summary = chain.run_repair_chain(
        options,
        runner=runner,
        project_validator=lambda _project, _revision: attestation,
        environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
    )

    assert summary["status"] == "merged"
    assert options.merged_output_dir.is_dir()
    assert {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    } == source_bytes


def test_repair_chain_zero_owed_finalizes_original_only(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    runner = FakeRunner(0, options.source_dir, attestation)

    summary = chain.run_repair_chain(
        options,
        runner=runner,
        project_validator=lambda _project, _revision: attestation,
        environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
    )

    assert summary["status"] == "finalized_without_repair"
    assert summary["repair_count"] == 0
    assert runner.stages == ["materialize", "finalize_original"]
    assert options.original_export_dir.is_dir()
    assert not options.repair_export_dir.exists()
    assert not options.merged_output_dir.exists()


def test_child_failure_is_redacted_and_logs_are_private(tmp_path: Path) -> None:
    log_dir = tmp_path / "private" / "logs"
    log_dir.mkdir(parents=True)
    secret = "opaque-child-payload-must-not-escape"
    command = chain.ChildCommand(
        stage="repair_eval",
        argv=(
            sys.executable,
            "-c",
            f"import sys; print({secret!r}); print({secret!r}, file=sys.stderr); raise SystemExit(9)",
        ),
        environment={"PATH": os.environ["PATH"], "PROJECT_DIR": str(tmp_path)},
        expects_summary=False,
    )

    with pytest.raises(chain.RepairChainError, match="^repair_eval_failed$") as failure:
        chain._run_child(command, log_dir)

    assert secret not in str(failure.value)
    logs = sorted(log_dir.iterdir())
    assert len(logs) == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in logs)
    assert all(secret in path.read_text() for path in logs)


def test_repair_chain_rejects_existing_output_without_running_child(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    options.merged_output_dir.mkdir()
    runner = FakeRunner(2, options.source_dir, attestation)

    with pytest.raises(chain.RepairChainError, match="^merged_output_path_unsafe$"):
        chain.run_repair_chain(
            options,
            runner=runner,
            project_validator=lambda _project, _revision: attestation,
            environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
        )

    assert runner.stages == []
    assert not options.runtime_dir.exists()


def test_repair_chain_detects_source_mutation(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    runner = FakeRunner(0, options.source_dir, attestation, mutate_source=True)

    with pytest.raises(chain.RepairChainError, match="^original_source_changed$"):
        chain.run_repair_chain(
            options,
            runner=runner,
            project_validator=lambda _project, _revision: attestation,
            environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
        )

    assert runner.stages == ["materialize"]
    assert not options.original_export_dir.exists()


def test_repair_chain_detects_selection_mutation(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    runner = FakeRunner(2, options.source_dir, attestation, mutate_selection=True)

    with pytest.raises(chain.RepairChainError, match="^repair_selection_changed$"):
        chain.run_repair_chain(
            options,
            runner=runner,
            project_validator=lambda _project, _revision: attestation,
            environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
        )
    assert runner.stages == ["materialize", "repair_eval"]
    assert not options.original_export_dir.exists()


@pytest.mark.parametrize(
    ("role", "error_code"),
    [
        ("original", "original_export_changed"),
        ("repair", "repair_export_changed"),
    ],
)
def test_repair_chain_rejects_export_mutation_between_finalization_and_merge(
    tmp_path: Path,
    role: str,
    error_code: str,
) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    runner = FakeRunner(
        2,
        options.source_dir,
        attestation,
        mutate_original_export_on_merge=role == "original",
        mutate_repair_export_on_merge=role == "repair",
    )

    with pytest.raises(chain.RepairChainError, match=f"^{error_code}$"):
        chain.run_repair_chain(
            options,
            runner=runner,
            project_validator=lambda _project, _revision: attestation,
            environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
        )

    assert runner.stages[-1] == "merge"
    assert not options.merged_output_dir.exists()


def test_repair_chain_revalidates_project_before_direct_repair(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    runner = FakeRunner(1, options.source_dir, attestation)
    calls = 0

    def validate(_project: Path, _revision: str) -> chain.ProjectAttestation:
        nonlocal calls
        calls += 1
        if calls < 4:
            return attestation
        return chain.ProjectAttestation(
            revision=attestation.revision,
            submodules=attestation.submodules,
            materializer_sha256="d" * 64,
            exporter_sha256=attestation.exporter_sha256,
            repair_template_sha256=attestation.repair_template_sha256,
        )

    with pytest.raises(chain.RepairChainError, match="^project_attestation_mismatch$"):
        chain.run_repair_chain(
            options,
            runner=runner,
            project_validator=validate,
            environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
        )

    assert runner.stages == ["materialize"]


def test_repair_chain_source_snapshot_rejects_symlink(tmp_path: Path) -> None:
    options, attestation, _source_bytes = _layout(tmp_path)
    outside = tmp_path / "opaque-external"
    outside.write_bytes(b"opaque\n")
    (options.source_dir / "unexpected-link").symlink_to(outside)
    runner = FakeRunner(0, options.source_dir, attestation)

    with pytest.raises(chain.RepairChainError, match="^source_snapshot_failed$"):
        chain.run_repair_chain(
            options,
            runner=runner,
            project_validator=lambda _project, _revision: attestation,
            environment={"PATH": os.environ["PATH"], "SLURM_JOB_ID": "456"},
        )

    assert runner.stages == []
    assert not options.runtime_dir.exists()
