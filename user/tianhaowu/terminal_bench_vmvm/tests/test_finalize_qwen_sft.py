import fcntl
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import finalize_qwen_sft as finalizer
import pytest
from finalize_qwen_sft import FinalizationError, FinalizeOptions


def _write_layout(tmp_path: Path, *, expected_count: int = 3) -> tuple[FinalizeOptions, str]:
    project = tmp_path / "project"
    project.mkdir()
    source_root = tmp_path / "evals"
    source = source_root / "epoch3"
    source.mkdir(parents=True)
    output_root = tmp_path / "sft"
    output_root.mkdir()
    (source / ".direct_router.lock").touch()
    (source / ".writer.lock").touch()
    (source / "results.jsonl").write_bytes(b"synthetic\n")
    (source / "config.toml").write_text(f"num_tasks = {expected_count}\nnum_rollouts = 1\n")
    provenance = b"synthetic-provenance\n"
    (source / "provenance.txt").write_bytes(provenance)
    provenance_sha256 = hashlib.sha256(provenance).hexdigest()
    options = FinalizeOptions(
        project_dir=project,
        expected_project_revision="a" * 40,
        source_root=source_root,
        source_dir=source,
        expected_provenance_sha256=provenance_sha256,
        output_root=output_root,
        output_dir=output_root / "corpus",
        expected_count=expected_count,
        selection="pass-only",
        validation_permyriad=500,
        split_salt="synthetic-split-v1",
    )
    return options, provenance_sha256


def _label_summary(index: Path, expected_count: int) -> dict:
    index.write_bytes(b"synthetic-index\n")
    return {
        "ignored_incomplete_tail": False,
        "ok": True,
        "results_sha256": "b" * 64,
        "rows": expected_count,
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "epoch_1_rows": 1,
        "epoch_2_rows": 1,
        "epoch_3_rows": expected_count - 2,
    }


def _export_summary(output: Path, expected_count: int, routing_index: Path) -> dict:
    (output / "train").mkdir(parents=True)
    (output / "validation").mkdir()
    train = b"synthetic-train\n"
    validation = b"synthetic-validation\n"
    retained_index = routing_index.read_bytes()
    (output / "train" / "train.jsonl").write_bytes(train)
    (output / "validation" / "train.jsonl").write_bytes(validation)
    (output / finalizer.INDEX_FILENAME).write_bytes(retained_index)
    target_contract = (
        json.dumps(finalizer.exporter.TARGET_RENDERING_CONTRACT, indent=2, sort_keys=True).encode() + b"\n"
    )
    assert hashlib.sha256(target_contract).hexdigest() == finalizer.exporter.TARGET_RENDERING_CONTRACT_SHA256
    (output / finalizer.exporter.TARGET_RENDERING_CONTRACT_FILENAME).write_bytes(target_contract)
    manifest = (
        json.dumps(
            {
                "artifacts": {
                    finalizer.INDEX_FILENAME: {
                        "bytes": len(retained_index),
                        "sha256": hashlib.sha256(retained_index).hexdigest(),
                    },
                    finalizer.exporter.TARGET_RENDERING_CONTRACT_FILENAME: {
                        "bytes": len(target_contract),
                        "sha256": hashlib.sha256(target_contract).hexdigest(),
                    },
                },
                "target_rendering": finalizer.exporter.TARGET_RENDERING_CONTRACT,
            },
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    (output / "manifest.json").write_bytes(manifest)
    return {
        "approved_tasks": expected_count,
        "excluded_error_traces": 1,
        "input_traces": expected_count,
        "output_sha256": {
            "manifest": hashlib.sha256(manifest).hexdigest(),
            "routing_epoch_index": hashlib.sha256(retained_index).hexdigest(),
            "target_rendering_contract": hashlib.sha256(target_contract).hexdigest(),
            "train": hashlib.sha256(train).hexdigest(),
            "validation": hashlib.sha256(validation).hexdigest(),
        },
        "rows": {"total": 12, "train": 9, "validation": 3},
        "routing_epoch_rows": {"1": 4, "2": 5, "3": 3},
        "selected_traces": expected_count - 1,
        "selection": "pass-only",
        "status": "exported",
    }


def test_label_summary_rejects_unattested_incomplete_tail(tmp_path: Path) -> None:
    index = tmp_path / "qwen_router_epochs.jsonl"
    summary = _label_summary(index, 2)
    summary["ignored_incomplete_tail"] = True

    with pytest.raises(FinalizationError, match="^routing_index_summary_invalid$"):
        finalizer._validate_label_summary(summary, index, 3)


def test_finalizer_runs_label_before_export_and_emits_only_aggregates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _ = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")
    calls: list[tuple[list[str], str]] = []
    repository_checks: list[tuple[Path, str]] = []
    source_before = {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    }
    external_indexes: list[Path] = []
    staged_outputs: list[Path] = []

    def validate_repository(path: Path, revision: str) -> Path:
        repository_checks.append((path, revision))
        return path

    def audit_source(_source: Path, expected_count: int, _provenance_sha256: str) -> dict:
        assert expected_count == 3
        return {"routing_epoch": 3}

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        calls.append((command, code))
        if code == "routing_index_failed":
            assert command[2] == "label"
            assert "--repair-selection-manifest" not in command
            index = Path(command[command.index("--output") + 1])
            assert not index.is_relative_to(options.source_dir)
            external_indexes.append(index)
            return _label_summary(index, options.expected_count)
        assert code == "sft_export_failed"
        assert command[1].endswith("export_sft.py")
        index = Path(command[command.index("--routing-epoch-index") + 1])
        assert index == external_indexes[0]
        assert command[command.index("--expected-count") + 1] == "3"
        assert command[command.index("--selection") + 1] == "pass-only"
        staged_output = Path(command[command.index("--output-dir") + 1])
        assert staged_output != options.output_dir
        assert staged_output.parent == index.parent
        staged_outputs.append(staged_output)
        return _export_summary(staged_output, options.expected_count, index)

    summary = finalizer.finalize_qwen_sft(
        options,
        repository_validator=validate_repository,
        source_auditor=audit_source,
        command_runner=run_command,
    )

    assert [code for _command, code in calls] == ["routing_index_failed", "sft_export_failed"]
    assert len(repository_checks) == 4
    assert summary["status"] == "finalized"
    assert summary["input_traces"] == 3
    assert summary["routing_epoch_input_traces"] == {"epoch_1": 1, "epoch_2": 1, "epoch_3": 1}
    assert (options.output_dir / finalizer.INDEX_FILENAME).read_bytes() == b"synthetic-index\n"
    assert external_indexes and not external_indexes[0].exists()
    assert staged_outputs and not staged_outputs[0].exists()
    source_after = {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    }
    assert source_after == source_before
    encoded = json.dumps(summary)
    assert str(options.source_dir) not in encoded
    assert str(options.output_dir) not in encoded


def test_finalizer_passes_private_exclusion_and_rejects_toctou(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, _ = _write_layout(tmp_path)
    selection = tmp_path / "private" / "selection" / "repair_manifest.json"
    selection.parent.mkdir(parents=True)
    selection.write_bytes(b"synthetic-selection\n")
    selection.chmod(0o600)
    digest = hashlib.sha256(selection.read_bytes()).hexdigest()
    options = replace(
        base,
        exclusion_selection_manifest=selection,
        expected_exclusion_selection_manifest_sha256=digest,
    )
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        if code == "routing_index_failed":
            assert command[command.index("--repair-selection-manifest") + 1] == str(selection)
            assert command[command.index("--repair-selection-manifest-sha256") + 1] == digest
            index = Path(command[command.index("--output") + 1])
            return _label_summary(index, options.expected_count)
        assert command[command.index("--exclusion-selection-manifest") + 1] == str(selection)
        assert command[command.index("--exclusion-selection-manifest-sha256") + 1] == digest
        index = Path(command[command.index("--routing-epoch-index") + 1])
        output = Path(command[command.index("--output-dir") + 1])
        summary = _export_summary(output, options.expected_count, index)
        summary["exclusion"] = {
            "excluded_present_traces": 1,
            "missing_tasks": 0,
            "missing_or_errored_count": 1,
            "selection_manifest_sha256": digest,
            "strict_invalid_pass_count": 0,
            "union_count": 1,
        }
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["exclusion_selection"] = {
            "approved_task_count": options.expected_count,
            "manifest": {"bytes": selection.stat().st_size, "sha256": digest},
            "union_count": 1,
            "missing_or_errored_count": 1,
            "strict_invalid_pass_count": 0,
        }
        (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
        summary["output_sha256"]["manifest"] = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
        selection.write_bytes(b"mutated-selection\n")
        selection.chmod(0o600)
        return summary

    with pytest.raises(FinalizationError, match="^exclusion_selection_changed$"):
        finalizer.finalize_qwen_sft(
            options,
            repository_validator=lambda path, _revision: path,
            source_auditor=lambda *_args: {"routing_epoch": 3},
            command_runner=run_command,
        )
    assert not options.output_dir.exists()


def test_finalizer_accounts_for_attested_missing_source_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, _ = _write_layout(tmp_path)
    selection = tmp_path / "private" / "selection" / "repair_manifest.json"
    selection.parent.mkdir(parents=True)
    selection.write_bytes(b"synthetic-selection\n")
    selection.chmod(0o600)
    digest = hashlib.sha256(selection.read_bytes()).hexdigest()
    options = replace(
        base,
        exclusion_selection_manifest=selection,
        expected_exclusion_selection_manifest_sha256=digest,
    )
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        if code == "routing_index_failed":
            index = Path(command[command.index("--output") + 1])
            summary = _label_summary(index, 2)
            summary["ignored_incomplete_tail"] = True
            summary["epoch_1_rows"] = 0
            summary["epoch_2_rows"] = 0
            summary["epoch_3_rows"] = 2
            return summary
        index = Path(command[command.index("--routing-epoch-index") + 1])
        output = Path(command[command.index("--output-dir") + 1])
        summary = _export_summary(output, options.expected_count, index)
        summary["input_traces"] = 2
        summary["exclusion"] = {
            "excluded_present_traces": 0,
            "missing_tasks": 1,
            "missing_or_errored_count": 1,
            "selection_manifest_sha256": digest,
            "strict_invalid_pass_count": 0,
            "union_count": 1,
        }
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["exclusion_selection"] = {
            "approved_task_count": options.expected_count,
            "manifest": {"bytes": selection.stat().st_size, "sha256": digest},
            "union_count": 1,
            "missing_or_errored_count": 1,
            "strict_invalid_pass_count": 0,
        }
        (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
        summary["output_sha256"]["manifest"] = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
        return summary

    summary = finalizer.finalize_qwen_sft(
        options,
        repository_validator=lambda path, _revision: path,
        source_auditor=lambda *_args: {"routing_epoch": 3},
        command_runner=run_command,
    )
    assert summary["approved_tasks"] == 3
    assert summary["input_traces"] == 2
    assert summary["exclusion"]["missing_tasks"] == 1


def test_finalizer_cleans_staged_export_when_late_repository_check_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _ = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")
    source_before = {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    }
    repository_checks = 0

    def validate_repository(path: Path, _revision: str) -> Path:
        nonlocal repository_checks
        repository_checks += 1
        if repository_checks == 4:
            raise FinalizationError("project_not_clean")
        return path

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        if code == "routing_index_failed":
            index = Path(command[command.index("--output") + 1])
            return _label_summary(index, options.expected_count)
        index = Path(command[command.index("--routing-epoch-index") + 1])
        staged_output = Path(command[command.index("--output-dir") + 1])
        return _export_summary(staged_output, options.expected_count, index)

    with pytest.raises(FinalizationError, match="^project_not_clean$"):
        finalizer.finalize_qwen_sft(
            options,
            repository_validator=validate_repository,
            source_auditor=lambda *_args: {"routing_epoch": 3},
            command_runner=run_command,
        )

    assert not options.output_dir.exists()
    assert not list(options.output_dir.parent.glob(f".{options.output_dir.name}.finalize-*"))
    assert {
        path.relative_to(options.source_dir): path.read_bytes()
        for path in options.source_dir.rglob("*")
        if path.is_file()
    } == source_before


def test_finalizer_cleans_staged_export_when_summary_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _ = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")

    def run_command(command: list[str], _cwd: Path, code: str) -> dict:
        if code == "routing_index_failed":
            index = Path(command[command.index("--output") + 1])
            return _label_summary(index, options.expected_count)
        index = Path(command[command.index("--routing-epoch-index") + 1])
        staged_output = Path(command[command.index("--output-dir") + 1])
        summary = _export_summary(staged_output, options.expected_count, index)
        summary["selected_traces"] = options.expected_count + 1
        return summary

    with pytest.raises(FinalizationError, match="^sft_export_summary_invalid$"):
        finalizer.finalize_qwen_sft(
            options,
            repository_validator=lambda path, _revision: path,
            source_auditor=lambda *_args: {"routing_epoch": 3},
            command_runner=run_command,
        )

    assert not options.output_dir.exists()
    assert not list(options.output_dir.parent.glob(f".{options.output_dir.name}.finalize-*"))


def test_publish_output_never_replaces_existing_destination(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "artifact").write_text("new\n")
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_text("keep\n")

    with pytest.raises(FinalizationError, match="^output_already_exists$"):
        finalizer._publish_output(staged, destination)

    assert (staged / "artifact").read_text() == "new\n"
    assert sentinel.read_text() == "keep\n"


def test_publish_output_removes_its_directory_when_parent_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "artifact").write_text("new\n")
    destination = tmp_path / "destination"
    monkeypatch.setattr(
        finalizer,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("synthetic fsync failure")),
    )

    with pytest.raises(FinalizationError, match="^output_publish_failed$"):
        finalizer._publish_output(staged, destination)

    assert not destination.exists()


def test_finalizer_refuses_busy_source_lock(tmp_path: Path) -> None:
    options, _ = _write_layout(tmp_path)
    with (options.source_dir / ".writer.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(FinalizationError, match="^source_run_active$"):
            finalizer._source_locks_available(options.source_dir)


def test_finalizer_refuses_existing_output(tmp_path: Path) -> None:
    options, _ = _write_layout(tmp_path)
    options.output_dir.mkdir()

    with pytest.raises(FinalizationError, match="^output_path_unsafe$"):
        finalizer._resolve_paths(options)


def test_finalizer_does_not_claim_or_modify_a_source_sidecar(tmp_path: Path) -> None:
    options, _ = _write_layout(tmp_path)
    source_sidecar = options.source_dir / finalizer.INDEX_FILENAME
    source_sidecar.write_bytes(b"preexisting-source-sidecar\n")

    paths = finalizer._resolve_paths(options)

    assert paths.source_dir == options.source_dir
    assert source_sidecar.read_bytes() == b"preexisting-source-sidecar\n"


def test_finalizer_refuses_broad_or_overlapping_path_boundaries(tmp_path: Path) -> None:
    options, _ = _write_layout(tmp_path)
    broad = FinalizeOptions(
        **{**options.__dict__, "source_root": Path("/")},
    )
    with pytest.raises(FinalizationError, match="^path_boundary_unsafe$"):
        finalizer._resolve_paths(broad)

    overlapping = FinalizeOptions(
        **{**options.__dict__, "output_root": options.source_root, "output_dir": options.source_root / "new"},
    )
    with pytest.raises(FinalizationError, match="^path_boundaries_overlap$"):
        finalizer._resolve_paths(overlapping)


def test_source_audit_rejects_mismatched_provenance_before_parsing_config(tmp_path: Path) -> None:
    options, _ = _write_layout(tmp_path)
    with pytest.raises(FinalizationError, match="^source_provenance_digest_mismatch$"):
        finalizer._audit_source(options.source_dir, options.expected_count, "f" * 64)


def test_source_audit_requires_expected_count_and_epoch_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, provenance_sha256 = _write_layout(tmp_path)
    with pytest.raises(FinalizationError, match="^source_expected_count_mismatch$"):
        finalizer._audit_source(options.source_dir, options.expected_count + 1, provenance_sha256)

    monkeypatch.setattr(
        finalizer.direct,
        "audit_run_directory",
        lambda _source: {
            "routing_epoch": 2,
            "manifest_schema_version": finalizer.direct.ROUTER_MANIFEST_SCHEMA_VERSION,
            "router_policy": finalizer.direct.ROUTER_POLICY,
            "request_id_headers": list(finalizer.direct.ROUTER_REQUEST_ID_HEADERS),
            "provider_concurrency": finalizer.direct.PRODUCTION_PROVIDER_CONCURRENCY,
        },
    )
    with pytest.raises(FinalizationError, match="^source_not_routing_epoch_3$"):
        finalizer._audit_source(options.source_dir, options.expected_count, provenance_sha256)


def test_finalizer_requires_x86_64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options, _ = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "aarch64")
    with pytest.raises(FinalizationError, match="^x86_64_required$"):
        finalizer._validate_options(options)


def test_repository_validator_requires_exact_clean_revision(tmp_path: Path) -> None:
    project = tmp_path / "repository"
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    workflow.mkdir(parents=True)
    for name in ("finalize_qwen_sft.py", "migrate_qwen_router_affinity.py", "export_sft.py"):
        (workflow / name).write_text("# synthetic\n")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "synthetic",
        ],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    with pytest.raises(FinalizationError, match="^project_not_detached$"):
        finalizer._validate_repository(project, revision, required_submodules=())
    subprocess.run(["git", "-C", str(project), "checkout", "--detach", "-q"], check=True)

    assert finalizer._validate_repository(project, revision, required_submodules=()) == project
    with pytest.raises(FinalizationError, match="^project_revision_mismatch$"):
        finalizer._validate_repository(project, "0" * 40, required_submodules=())
    (project / "untracked").touch()
    with pytest.raises(FinalizationError, match="^project_not_clean$"):
        finalizer._validate_repository(project, revision, required_submodules=())


def test_child_failure_output_is_suppressed(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "import sys; print('sensitive row', file=sys.stderr); raise SystemExit(1)",
    ]
    with pytest.raises(FinalizationError, match="^child_failed$"):
        finalizer._run_json_command(command, tmp_path, "child_failed")


def test_main_reports_only_stable_error_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    def fail(_options: FinalizeOptions) -> dict:
        raise FinalizationError("source_run_active")

    monkeypatch.setattr(finalizer, "finalize_qwen_sft", fail)
    arguments = [
        "--project-dir",
        "/synthetic/project",
        "--expected-project-revision",
        "a" * 40,
        "--source-root",
        "/synthetic/evals",
        "--source-dir",
        "/synthetic/evals/run",
        "--expected-provenance-sha256",
        "b" * 64,
        "--output-root",
        "/synthetic/sft",
        "--output-dir",
        "/synthetic/sft/corpus",
        "--expected-count",
        "2500",
        "--selection",
        "pass-only",
        "--validation-permyriad",
        "500",
        "--split-salt",
        "synthetic-v1",
    ]

    assert finalizer.main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"code": "source_run_active", "status": "error"}


def test_missing_required_arguments_use_stable_error(capsys: pytest.CaptureFixture) -> None:
    assert finalizer.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"code": "arguments_invalid", "status": "error"}
