import fcntl
import hashlib
import json
import subprocess
import sys
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
        "ok": True,
        "results_sha256": "b" * 64,
        "rows": expected_count,
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "epoch_1_rows": 1,
        "epoch_2_rows": 1,
        "epoch_3_rows": expected_count - 2,
    }


def _export_summary(output: Path, expected_count: int) -> dict:
    output.mkdir()
    manifest = b"{}\n"
    (output / "manifest.json").write_bytes(manifest)
    return {
        "excluded_error_traces": 1,
        "input_traces": expected_count,
        "output_sha256": {
            "manifest": hashlib.sha256(manifest).hexdigest(),
            "train": "c" * 64,
            "validation": "d" * 64,
        },
        "rows": {"total": 12, "train": 9, "validation": 3},
        "routing_epoch_rows": {"1": 4, "2": 5, "3": 3},
        "selected_traces": expected_count - 1,
        "selection": "pass-only",
        "status": "exported",
    }


def test_finalizer_runs_label_before_export_and_emits_only_aggregates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options, _ = _write_layout(tmp_path)
    monkeypatch.setattr(finalizer.platform, "machine", lambda: "x86_64")
    calls: list[tuple[list[str], str]] = []
    repository_checks: list[tuple[Path, str]] = []

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
            return _label_summary(options.source_dir / finalizer.INDEX_FILENAME, options.expected_count)
        assert code == "sft_export_failed"
        assert command[1].endswith("export_sft.py")
        assert command[command.index("--routing-epoch-index") + 1] == str(options.source_dir / finalizer.INDEX_FILENAME)
        assert command[command.index("--expected-count") + 1] == "3"
        assert command[command.index("--selection") + 1] == "pass-only"
        return _export_summary(options.output_dir, options.expected_count)

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
    encoded = json.dumps(summary)
    assert str(options.source_dir) not in encoded
    assert str(options.output_dir) not in encoded


def test_finalizer_refuses_busy_source_lock(tmp_path: Path) -> None:
    options, _ = _write_layout(tmp_path)
    with (options.source_dir / ".writer.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(FinalizationError, match="^source_run_active$"):
            finalizer._source_locks_available(options.source_dir)


@pytest.mark.parametrize("existing", ["index", "output"])
def test_finalizer_refuses_existing_artifacts(tmp_path: Path, existing: str) -> None:
    options, _ = _write_layout(tmp_path)
    if existing == "index":
        (options.source_dir / finalizer.INDEX_FILENAME).touch()
        expected = "routing_index_already_exists"
    else:
        options.output_dir.mkdir()
        expected = "output_path_unsafe"

    with pytest.raises(FinalizationError, match=f"^{expected}$"):
        finalizer._resolve_paths(options)


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
