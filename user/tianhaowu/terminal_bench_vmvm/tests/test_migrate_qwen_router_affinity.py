from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import tomllib
from pathlib import Path

import direct_qwen_workers as direct
import migrate_qwen_router_affinity as migration
import pytest
from validate_task_approval import validate_approval


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("COMPLETED", "COMPLETED"),
        ("OUT_OF_MEMORY", "OUT_OF_MEMORY"),
        ("CANCELLED by 656177", "CANCELLED"),
        ("  CANCELLED by 0  ", "CANCELLED"),
        ("RUNNING", "RUNNING"),
    ],
)
def test_normalize_slurm_state_accepts_only_canonical_forms(
    raw: str,
    expected: str,
) -> None:
    assert migration._normalize_slurm_state(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "cancelled by 656177",
        "CANCELLED by root",
        "CANCELLED by -1",
        "CANCELLED by 656177 extra",
        "FAILED by 656177",
        "CANCELLED+",
        "OUT_OF_ME+",
    ],
)
def test_normalize_slurm_state_rejects_ambiguous_suffixes(raw: str) -> None:
    assert migration._normalize_slurm_state(raw) is None


def test_slurm_terminal_check_accepts_cancelled_by_numeric_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str]) -> str:
        assert command[0] == "sacct"
        assert command[-1] == "--format=State%64"
        return "CANCELLED by 656177|\n"

    monkeypatch.setattr(migration, "_run", fake_run)
    assert migration.slurm_job_is_terminal("1448128") is True


@pytest.mark.parametrize("state", ["RUNNING", "CANCELLED by root", "COMPLETED+"])
def test_slurm_terminal_check_fails_closed_on_nonterminal_or_malformed_state(
    state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        migration,
        "_run",
        lambda _command: f"{state}|\n",
    )
    assert migration.slurm_job_is_terminal("1448128") is False


@pytest.mark.parametrize(
    "sacct_output",
    ["", "UNKNOWN|\n", "PENDING|\n", "COMPLETED|\nRUNNING|\n"],
)
def test_slurm_terminal_check_rejects_missing_unknown_or_mixed_states(
    sacct_output: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        calls.append(command)
        return sacct_output

    monkeypatch.setattr(migration, "_run", fake_run)
    assert migration.slurm_job_is_terminal("1448128") is False
    assert len(calls) == 1
    assert calls[0][0] == "sacct"


def _write_source_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, list[direct.Worker], str, str]:
    deployment = tmp_path / "deployment"
    endpoints = deployment / "endpoints"
    endpoints.mkdir(parents=True)
    (deployment / "spec.yaml").write_text("model: qwen\n")
    for index in range(2):
        (endpoints / f"{100 + index}.json").write_text(
            json.dumps(
                {
                    "host": f"worker-{index}",
                    "port": 20_000 + index,
                    "started_at": "2026-09-16T00:00:00Z",
                }
            )
            + "\n"
        )
    spec_sha256 = _sha256(deployment / "spec.yaml")
    bundle_sha256 = direct.endpoint_bundle_sha256(sorted(endpoints.iterdir()))
    workers, _, _ = direct.load_workers(
        deployment,
        expected_spec_sha256=spec_sha256,
        expected_bundle_sha256=bundle_sha256,
        expected_count=2,
    )
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", 2)

    source = tmp_path / "source"
    inputs = source / "inputs"
    inputs.mkdir(parents=True)
    (source / ".direct_router.lock").write_bytes(b"")
    (source / ".writer.lock").write_bytes(b"")
    original_repository = tmp_path / "original-repository"
    relative_task_file = Path("user/fixture/approved.txt")
    original_task_file = original_repository / relative_task_file
    original_task_file.parent.mkdir(parents=True)
    original_task_file.write_text("fixture-a\nfixture-b\n")
    task_file = inputs / "task_file.txt"
    task_file.write_bytes(original_task_file.read_bytes())
    task_sha256 = _sha256(task_file)

    template_config_path = Path(__file__).parents[1] / "configs" / "eval" / "tb4_qwen_token_smoke.toml"
    source_config = tomllib.loads(template_config_path.read_text())
    old_task_file = source_config["taskset"]["task_file"]
    old_task_sha256 = source_config["taskset"]["task_file_sha256"]
    source_config_text = (
        template_config_path.read_text()
        .replace(
            f'task_file = "{old_task_file}"',
            f'task_file = "{relative_task_file}"',
        )
        .replace(
            f'task_file_sha256 = "{old_task_sha256}"',
            f'task_file_sha256 = "{task_sha256}"',
        )
    )
    original_config_path = original_repository / "user" / "fixture" / "config.toml"
    original_config_path.write_text(source_config_text)
    config_text = source_config_text.replace(
        f'task_file = "{relative_task_file}"',
        f'task_file = "{task_file}"',
    ).replace(
        'base_url = "http://127.0.0.1:8000/v1"',
        'base_url = "http://127.0.0.1:20001/v1"',
    )
    (source / "config.toml").write_text(config_text)
    (inputs / "source_config.toml").write_text(source_config_text)
    (inputs / "manifest.json").write_text(
        json.dumps(
            {
                "config": {
                    "source": str(original_config_path),
                    "snapshot": str(inputs / "source_config.toml"),
                    "sha256": _sha256(inputs / "source_config.toml"),
                },
                "task_file": {
                    "source": str(original_task_file),
                    "snapshot": str(task_file),
                    "sha256": task_sha256,
                },
            }
        )
        + "\n"
    )
    manifest = direct._manifest(
        deployment,
        workers,
        spec_sha256,
        bundle_sha256,
        task_sha256,
        20_001,
        40_001,
        2,
    )
    manifest["schema_version"] = 1
    manifest["router"]["policy"] = "round_robin"
    manifest["router"].pop("request_id_headers")
    (source / "direct_workers.json").write_text(json.dumps(manifest) + "\n")
    (source / "provenance.txt").write_text(
        "prime_rl=" + "1" * 40 + "\n"
        "verifiers=" + "2" * 40 + "\n"
        "renderers=" + "3" * 40 + "\n"
        "inference_base_url=http://127.0.0.1:20001/v1\n"
        "inference_deployment_id=\n"
        "slurm_job_id=123\n"
    )
    rows = [
        {"task": {"idx": 0}, "errors": []},
        {"task": {"idx": 1}, "errors": [{"type": "synthetic"}]},
        {"task": {"idx": 0}, "errors": []},
    ]
    (source / "results.jsonl").write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))
    (source / "direct_router.log").write_text("legacy log\n")
    return source, deployment, workers, spec_sha256, bundle_sha256


def test_migrate_is_copy_on_write_and_resume_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, deployment, workers, spec_sha256, bundle_sha256 = _write_source_run(
        tmp_path,
        monkeypatch,
    )
    source_hashes = {relative: _sha256(source / relative) for relative in migration.REQUIRED_SOURCE_FILES}
    child = tmp_path / "child"

    def unsupported_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EINVAL, "filesystem does not support RENAME_NOREPLACE")

    monkeypatch.setattr(migration, "_rename_noreplace", unsupported_rename)

    summary = migration.migrate(source, child, terminal_check=lambda _job_id: True)

    assert summary["retained_rows"] == 1
    assert summary["owed_rollouts"] == 1
    assert all(_sha256(source / relative) == digest for relative, digest in source_hashes.items())
    assert json.loads((source / "direct_workers.json").read_text())["schema_version"] == 1
    child_manifest = direct.validate_saved_manifest(child / "direct_workers.json")
    assert child_manifest["schema_version"] == 2
    assert child_manifest["router"]["policy"] == "consistent_hash"
    assert child_manifest["router"]["request_id_headers"] == ["x-session-id"]
    assert (child / "direct_workers.epoch-1.json").read_bytes() == (source / "direct_workers.json").read_bytes()
    assert (child / "direct_router.epoch-1.log").is_file()
    assert not (child / "direct_router.log").exists()
    assert not (child / direct.MIGRATION_INCOMPLETE_FILENAME).exists()
    assert (child / "inputs" / direct.ROUTING_EPOCH1_SOURCE_CONFIG_FILENAME).read_bytes() == (
        source / "inputs" / "source_config.toml"
    ).read_bytes()
    assert len((child / "results.jsonl").read_text().splitlines()) == 1
    child_config = tomllib.loads((child / "config.toml").read_text())
    assert Path(child_config["taskset"]["task_file"]) == child / "inputs" / "task_file.txt"
    child_inputs_manifest = json.loads((child / "inputs" / "manifest.json").read_text())
    assert Path(child_inputs_manifest["config"]["snapshot"]) == child / "inputs" / "source_config.toml"
    assert child_inputs_manifest["config"]["sha256"] == _sha256(child / "inputs" / "source_config.toml")
    assert Path(child_inputs_manifest["task_file"]["snapshot"]) == child / "inputs" / "task_file.txt"
    assert Path(child_inputs_manifest["task_file"]["source"]) == child / "inputs" / "task_file.txt"
    transition = json.loads((child / direct.ROUTING_TRANSITION_FILENAME).read_text())
    assert transition["child"]["config_sha256"] == _sha256(child / "config.toml")
    assert transition["source"]["source_config_sha256"] == _sha256(source / "inputs" / "source_config.toml")
    assert transition["child"]["source_config_sha256"] == _sha256(child / "inputs" / "source_config.toml")
    assert transition["child"]["inputs_manifest_sha256"] == _sha256(child / "inputs" / "manifest.json")
    validate_approval(
        child / "inputs",
        child / "inputs" / "task_file.txt",
        _sha256(child / "inputs" / "task_file.txt"),
        resume_config=child / "config.toml",
    )
    assert direct.audit_run_directory(child)["routing_epoch"] == 2

    monkeypatch.setattr(
        direct,
        "load_workers",
        lambda _root: (workers, spec_sha256, bundle_sha256),
    )
    monkeypatch.setattr(direct, "probe_workers", lambda *_args, **_kwargs: None)
    resumed = direct.prepare(
        deployment,
        child / "config.toml",
        child / "direct_workers.json",
        tmp_path / "resume-urls.txt",
        tmp_path / "resume-runtime.txt",
        child / "inputs" / "task_file.txt",
        _sha256(child / "inputs" / "task_file.txt"),
        resume=True,
        probe_timeout=1,
    )
    assert resumed == child_manifest


def test_fallback_cleans_destination_after_ordinary_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "artifact").write_text("complete\n")
    destination = tmp_path / "destination"
    monkeypatch.setattr(
        migration,
        "_rename_noreplace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError(errno.EINVAL, "unsupported")),
    )

    with pytest.raises(migration.MigrationError, match="synthetic_validation_failure"):
        migration._publish_directory(
            staged,
            destination,
            lambda _path, _allow_incomplete: (_ for _ in ()).throw(
                migration.MigrationError("synthetic_validation_failure")
            ),
        )

    assert staged.is_dir()
    assert not destination.exists()


def test_fallback_crash_leaves_marker_that_launchers_reject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "artifact").write_text("complete\n")
    destination = tmp_path / "destination"
    monkeypatch.setattr(
        migration,
        "_rename_noreplace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError(errno.EINVAL, "unsupported")),
    )

    with pytest.raises(KeyboardInterrupt):
        migration._publish_directory(
            staged,
            destination,
            lambda _path, allow_incomplete: (_ for _ in ()).throw(KeyboardInterrupt()) if allow_incomplete else None,
        )

    marker = destination / direct.MIGRATION_INCOMPLETE_FILENAME
    assert marker.is_file()
    with pytest.raises(direct.DirectWorkerError, match="migration_incomplete"):
        direct.audit_run_directory(destination)
    with pytest.raises(direct.DirectWorkerError, match="migration_incomplete"):
        direct.prepare(
            tmp_path,
            destination / "config.toml",
            destination / "direct_workers.json",
            tmp_path / "urls.txt",
            tmp_path / "runtime.txt",
            tmp_path / "tasks.txt",
            "a" * 64,
            resume=True,
            probe_timeout=1,
        )


def test_migrate_refuses_busy_source_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    with (source / ".writer.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(migration.MigrationError, match="source_lock_busy"):
            migration.migrate(source, child, terminal_check=lambda _job_id: True)
    assert not child.exists()


def test_migrate_refuses_nonterminal_job_and_existing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    with pytest.raises(migration.MigrationError, match="not_terminal"):
        migration.migrate(source, child, terminal_check=lambda _job_id: False)
    assert not child.exists()

    child.mkdir()
    with pytest.raises(migration.MigrationError, match="destination_exists"):
        migration.migrate(source, child, terminal_check=lambda _job_id: True)


def test_transition_drift_is_rejected_before_worker_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, deployment, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    migration.migrate(source, child, terminal_check=lambda _job_id: True)
    transition_path = child / direct.ROUTING_TRANSITION_FILENAME
    transition = json.loads(transition_path.read_text())
    transition["resume_plan"]["retained_row_count"] += 1
    transition_path.write_text(json.dumps(transition) + "\n")
    probes = 0

    def forbidden_load(_root: Path):
        nonlocal probes
        probes += 1
        raise AssertionError("worker metadata must not be read after lineage drift")

    monkeypatch.setattr(direct, "load_workers", forbidden_load)
    with pytest.raises(direct.DirectWorkerError, match="provenance_hash_mismatch"):
        direct.prepare(
            deployment,
            child / "config.toml",
            child / "direct_workers.json",
            tmp_path / "resume-urls.txt",
            tmp_path / "resume-runtime.txt",
            child / "inputs" / "task_file.txt",
            _sha256(child / "inputs" / "task_file.txt"),
            resume=True,
            probe_timeout=1,
        )
    assert probes == 0


def test_epoch_index_labels_legacy_membership_after_result_reordering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    migration.migrate(source, child, terminal_check=lambda _job_id: True)
    manifest_sha256 = _sha256(child / "direct_workers.json")
    with (child / "provenance.txt").open("a") as provenance:
        for job_id in (124, 125):
            provenance.write(
                f"resume_slurm_job_id={job_id}\n"
                f"resume_direct_qwen_manifest_sha256={manifest_sha256}\n"
                "resume_direct_qwen_router_policy=consistent_hash\n"
                "resume_direct_qwen_request_id_headers=x-session-id\n"
            )
    epoch1_row = (child / "results.jsonl").read_bytes()
    epoch2_row = (json.dumps({"task": {"idx": 1}, "errors": []}, sort_keys=True) + "\n").encode()
    (child / "results.jsonl").write_bytes(epoch2_row + epoch1_row)
    index_path = child / "qwen_router_epochs.jsonl"

    summary = migration.label_routing_epochs(
        child,
        index_path,
        terminal_check=lambda _job_id: True,
    )

    assert summary["rows"] == 2
    assert summary["epoch_1_rows"] == 1
    assert summary["epoch_2_rows"] == 1
    index = [json.loads(line) for line in index_path.read_text().splitlines()]
    assert index[0]["kind"] == "qwen-routing-epoch-index"
    assert index[0]["results_sha256"] == summary["results_sha256"]
    assert [record["routing_epoch"] for record in index[1:]] == [2, 1]
    assert all(set(record) == {"row", "row_sha256", "routing_epoch"} for record in index[1:])
