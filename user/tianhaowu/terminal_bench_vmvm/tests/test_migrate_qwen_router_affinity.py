from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

import direct_qwen_workers as direct
import migrate_qwen_router_affinity as migration
import pytest
from validate_task_approval import validate_approval


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tail_selection(tmp_path: Path, results: Path) -> tuple[Path, str]:
    selection = tmp_path / "repair_manifest.json"
    body = (
        json.dumps(
            {
                "kind": migration.REPAIR_SELECTION_KIND,
                "schema_version": migration.REPAIR_SELECTION_SCHEMA_VERSION,
                "selection": {"missing_or_errored_count": 1},
                "source": {
                    "artifacts": {
                        "results": {
                            "sha256": _sha256(results),
                            "size_bytes": results.stat().st_size,
                        }
                    }
                },
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    selection.write_bytes(body)
    selection.chmod(0o600)
    return selection, hashlib.sha256(body).hexdigest()


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
    *,
    production: bool = False,
    verifiers_revision: str = "2" * 40,
) -> tuple[Path, Path, list[direct.Worker], str, str]:
    monkeypatch.setattr(migration, "_repository_revision", lambda: "4" * 40)
    deployment = tmp_path / "deployment"
    endpoints = deployment / "endpoints"
    endpoints.mkdir(parents=True)
    (deployment / "spec.yaml").write_text("model: qwen\n")
    endpoint_count = 16 if production else 2
    for index in range(endpoint_count):
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
        expected_count=endpoint_count,
    )
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", endpoint_count)

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

    template_config_path = (
        Path(__file__).parents[1]
        / "configs"
        / "eval"
        / ("mobius_qwen_a95b_2500.toml" if production else "tb4_qwen_token_smoke.toml")
    )
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
    source_config_text = source_config_text.replace(', "InterceptionError"', "")
    if production:
        relative_image_manifest = Path("user/fixture/images.json")
        original_image_manifest = original_repository / relative_image_manifest
        original_image_manifest.write_text("{}\n")
        image_manifest = inputs / "image_manifest.json"
        image_manifest.write_bytes(original_image_manifest.read_bytes())
        old_image_manifest = source_config["taskset"]["image_manifest"]
        old_image_sha256 = source_config["taskset"]["image_manifest_sha256"]
        image_sha256 = _sha256(image_manifest)
        source_config_text = (
            source_config_text.replace("num_tasks = 2500", "num_tasks = 2")
            .replace("max_connections = 32", "max_connections = 16")
            .replace("max_keepalive_connections = 32", "max_keepalive_connections = 16")
            .replace(f'image_manifest = "{old_image_manifest}"', f'image_manifest = "{relative_image_manifest}"')
            .replace(f'image_manifest_sha256 = "{old_image_sha256}"', f'image_manifest_sha256 = "{image_sha256}"')
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
    if production:
        config_text = config_text.replace(
            f'image_manifest = "{relative_image_manifest}"',
            f'image_manifest = "{image_manifest}"',
        )
    (source / "config.toml").write_text(config_text)
    (inputs / "source_config.toml").write_text(source_config_text)
    input_manifest = {
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
    if production:
        input_manifest["image_manifest"] = {
            "source": str(original_image_manifest),
            "snapshot": str(image_manifest),
            "sha256": image_sha256,
        }
    (inputs / "manifest.json").write_text(json.dumps(input_manifest) + "\n")
    manifest = direct._manifest(
        deployment,
        workers,
        spec_sha256,
        bundle_sha256,
        task_sha256,
        20_001,
        40_001,
        64 if production else 2,
        16 if production else 2,
    )
    manifest["schema_version"] = 1
    manifest.pop("admission")
    manifest["router"]["policy"] = "round_robin"
    manifest["router"].pop("request_id_headers")
    (source / "direct_workers.json").write_text(json.dumps(manifest) + "\n")
    (source / "provenance.txt").write_text(
        "prime_rl=" + "1" * 40 + "\n"
        "verifiers=" + verifiers_revision + "\n"
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
    assert child_manifest["schema_version"] == direct.AFFINITY_MANIFEST_SCHEMA_VERSION
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


def test_migrate_admission_is_copy_on_write_and_preserves_full_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, deployment, workers, spec_sha256, bundle_sha256 = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    (epoch2 / "qwen_router_epochs.jsonl").write_text("stale\n")
    with (epoch2 / "results.jsonl").open("ab") as results:
        results.write(b'{"incomplete"')
    with pytest.raises(direct.DirectWorkerError, match="admission_epoch_migration_required"):
        direct.prepare(
            deployment,
            epoch2 / "config.toml",
            epoch2 / "direct_workers.json",
            tmp_path / "blocked-urls.txt",
            tmp_path / "blocked-runtime.txt",
            epoch2 / "inputs" / "task_file.txt",
            _sha256(epoch2 / "inputs" / "task_file.txt"),
            resume=True,
            probe_timeout=1,
        )
    source_hashes = {relative: _sha256(epoch2 / relative) for relative in migration.REQUIRED_SOURCE_FILES}
    parent_transition = (epoch2 / direct.ROUTING_TRANSITION_FILENAME).read_bytes()
    epoch3 = tmp_path / "epoch3"

    summary = migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)

    assert summary["routing_epoch"] == 3
    assert summary["provider_concurrency"] == 32
    assert summary["queue_size"] == 32
    assert all(_sha256(epoch2 / relative) == digest for relative, digest in source_hashes.items())
    assert (epoch3 / direct.ROUTING_TRANSITION_FILENAME).read_bytes() == parent_transition
    assert not (epoch3 / "qwen_router_epochs.jsonl").exists()
    assert (epoch3 / direct.ROUTING_EPOCH2_MANIFEST_FILENAME).read_bytes() == (
        epoch2 / "direct_workers.json"
    ).read_bytes()
    assert (epoch3 / direct.ROUTING_EPOCH2_CONFIG_FILENAME).read_bytes() == (epoch2 / "config.toml").read_bytes()
    assert (epoch3 / direct.ROUTING_EPOCH2_PROVENANCE_FILENAME).read_bytes() == (epoch2 / "provenance.txt").read_bytes()
    manifest = direct.validate_saved_manifest(epoch3 / "direct_workers.json")
    assert manifest["schema_version"] == direct.ROUTER_MANIFEST_SCHEMA_VERSION
    assert manifest["router"]["max_concurrent_requests"] == 32
    assert manifest["router"]["queue_size"] == 32
    assert manifest["admission"]["client_max_connections"] == 32
    config = tomllib.loads((epoch3 / "config.toml").read_text())
    assert config["max_concurrent"] == config["multiplex"] == 64
    assert config["client"]["max_connections"] == 32
    assert config["client"]["max_keepalive_connections"] == 32
    transition = json.loads((epoch3 / direct.ADMISSION_TRANSITION_FILENAME).read_text())
    assert transition["resume_plan"]["planner_verifiers_revision"] == migration.EXPECTED_VERIFIERS_REVISION
    assert transition["resume_plan"]["planner_module_sha256"] == migration.EXPECTED_RESUME_MODULE_SHA256
    assert transition["resume_plan"]["group"] is False
    assert transition["resume_plan"]["shuffle"] is False
    assert transition["resume_plan"]["require_exact_tokens"] is False
    assert transition["resume_plan"]["require_logprobs"] is False
    lineage = direct._read_epoch2_lineage(epoch3 / direct.ROUTING_EPOCH2_ROWS_FILENAME)
    assert len(lineage) == summary["retained_rows"] == 1
    assert lineage[0]["routing_epoch"] == 1
    assert direct.audit_run_directory(epoch3)["routing_epoch"] == 3

    monkeypatch.setattr(direct, "load_workers", lambda _root: (workers, spec_sha256, bundle_sha256))
    monkeypatch.setattr(direct, "probe_workers", lambda *_args, **_kwargs: None)
    resumed = direct.prepare(
        deployment,
        epoch3 / "config.toml",
        epoch3 / "direct_workers.json",
        tmp_path / "epoch3-urls.txt",
        tmp_path / "epoch3-runtime.txt",
        epoch3 / "inputs" / "task_file.txt",
        _sha256(epoch3 / "inputs" / "task_file.txt"),
        resume=True,
        probe_timeout=1,
    )
    assert resumed == manifest
    provenance_path = epoch3 / "provenance.txt"
    provenance_bytes = provenance_path.read_bytes()
    provenance_path.write_bytes(
        provenance_bytes.replace(b"direct_qwen_provider_concurrency=32", b"direct_qwen_provider_concurrency=31")
    )
    with pytest.raises(direct.DirectWorkerError, match="provenance_router_mismatch"):
        direct.audit_run_directory(epoch3)
    provenance_path.write_bytes(provenance_bytes)

    manifest_sha256 = _sha256(epoch3 / "direct_workers.json")
    with provenance_path.open("a") as provenance_file:
        for job_id in (124, 125):
            provenance_file.write(
                f"resume_slurm_job_id={job_id}\n"
                f"resume_direct_qwen_manifest_sha256={manifest_sha256}\n"
                "resume_direct_qwen_router_policy=consistent_hash\n"
                "resume_direct_qwen_request_id_headers=x-session-id\n"
                "resume_direct_qwen_provider_concurrency=32\n"
            )
    retained = (epoch3 / "results.jsonl").read_bytes()
    epoch3_row = (json.dumps({"task": {"idx": 1}, "errors": []}, sort_keys=True) + "\n").encode()
    (epoch3 / "results.jsonl").write_bytes(epoch3_row + retained)
    sidecars = tmp_path / "epoch3-sidecars"
    sidecars.mkdir()
    label_summary = migration.label_routing_epochs(
        epoch3,
        sidecars / "qwen_router_epochs.jsonl",
        terminal_check=lambda _job_id: True,
    )
    assert label_summary["epoch_1_rows"] == 1
    assert label_summary["epoch_2_rows"] == 0
    assert label_summary["epoch_3_rows"] == 1


def test_admission_planner_materializes_exact_pinned_offsets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {"task": {"idx": 0}, "errors": []},
        {"task": {"idx": 1}, "errors": [{"type": "synthetic"}]},
        {"task": {"idx": 1}, "errors": []},
        {"task": {"idx": 0}, "errors": []},
    ]
    payloads = [(json.dumps(row, sort_keys=True) + "\n").encode() for row in rows]
    offsets: list[int] = []
    position = 0
    for payload in payloads:
        offsets.append(position)
        position += len(payload)
    (run / "results.jsonl").write_bytes(b"".join(payloads))

    class FakeResume:
        @staticmethod
        def plan(
            resume_dir: Path,
            selected_idxs: list[int],
            num_rollouts: int,
            group: bool,
            *,
            require_exact_tokens: bool,
            require_logprobs: bool,
        ) -> tuple[list[int], dict[int, int]]:
            assert resume_dir == run
            assert selected_idxs == [0, 1, 2]
            assert num_rollouts == 1
            assert group is require_exact_tokens is require_logprobs is False
            return [offsets[2], offsets[0]], {2: 1}

    monkeypatch.setattr(migration, "_load_verifiers_resume", lambda _revision: FakeResume)
    retained = tmp_path / "retained.jsonl"
    lineage = tmp_path / "lineage.jsonl"
    epoch1_digest = hashlib.sha256(payloads[0]).hexdigest()

    summary = migration._plan_retained_results_with_verifiers(
        run / "results.jsonl",
        retained,
        lineage,
        3,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
        epoch1_hashes={epoch1_digest},
    )

    assert retained.read_bytes() == payloads[2] + payloads[0]
    assert summary["retained_row_count"] == 2
    assert summary["owed_rollout_count"] == 1
    records = [json.loads(line) for line in lineage.read_text().splitlines()]
    assert [record["routing_epoch"] for record in records] == [2, 1]
    assert all(set(record) == {"row_sha256", "routing_epoch"} for record in records)


def test_admission_planner_rejects_selected_error_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    payload = (json.dumps({"task": {"idx": 0}, "errors": [{"type": "synthetic"}]}) + "\n").encode()
    (run / "results.jsonl").write_bytes(payload)

    class BadResume:
        @staticmethod
        def plan(*_args, **_kwargs) -> tuple[list[int], dict[int, int]]:
            return [0], {}

    monkeypatch.setattr(migration, "_load_verifiers_resume", lambda _revision: BadResume)
    with pytest.raises(migration.MigrationError, match="selected_unusable_row"):
        migration._plan_retained_results_with_verifiers(
            run / "results.jsonl",
            tmp_path / "retained.jsonl",
            tmp_path / "lineage.jsonl",
            1,
            verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
            epoch1_hashes=set(),
        )


@pytest.mark.parametrize(
    "relative",
    [
        direct.ROUTING_TRANSITION_FILENAME,
        direct.ADMISSION_TRANSITION_FILENAME,
        direct.ROUTING_EPOCH2_MANIFEST_FILENAME,
        direct.ROUTING_EPOCH2_CONFIG_FILENAME,
        direct.ROUTING_EPOCH2_PROVENANCE_FILENAME,
        f"inputs/{direct.ROUTING_EPOCH2_SOURCE_CONFIG_FILENAME}",
        f"inputs/{direct.ROUTING_EPOCH2_INPUTS_MANIFEST_FILENAME}",
        "inputs/image_manifest.json",
        direct.ROUTING_EPOCH2_ROWS_FILENAME,
        "config.toml",
        "direct_workers.json",
    ],
)
def test_admission_epoch_rejects_tampered_chain_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    path = epoch3 / relative
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(direct.DirectWorkerError):
        direct.audit_run_directory(epoch3)


def test_admission_epoch_rejects_duplicate_retained_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    results = epoch3 / "results.jsonl"
    first_row = results.open("rb").readline()
    results.write_bytes(results.read_bytes() + first_row)

    with pytest.raises(direct.DirectWorkerError, match="row_membership_mismatch"):
        direct.audit_run_directory(epoch3)


def test_policy_transition_rejects_boolean_schema_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    epoch2 = tmp_path / "epoch2"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    transition_path = epoch2 / direct.ROUTING_TRANSITION_FILENAME
    transition = json.loads(transition_path.read_text())
    transition["schema_version"] = True
    transition_path.write_text(json.dumps(transition, sort_keys=True) + "\n")
    provenance_path = epoch2 / "provenance.txt"
    provenance = provenance_path.read_text()
    provenance_path.write_text(
        provenance.replace(
            next(line for line in provenance.splitlines() if line.startswith("qwen_router_transition_sha256=")),
            f"qwen_router_transition_sha256={_sha256(transition_path)}",
        )
    )

    with pytest.raises(direct.DirectWorkerError, match="routing_transition_structure_invalid"):
        direct.audit_run_directory(epoch2)


def test_admission_transition_rejects_boolean_resume_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    transition_path = epoch3 / direct.ADMISSION_TRANSITION_FILENAME
    transition = json.loads(transition_path.read_text())
    transition["resume_plan"]["num_rollouts"] = True
    transition_path.write_text(json.dumps(transition, sort_keys=True) + "\n")
    provenance_path = epoch3 / "provenance.txt"
    provenance = provenance_path.read_text()
    provenance_path.write_text(
        provenance.replace(
            next(
                line for line in provenance.splitlines() if line.startswith("qwen_router_admission_transition_sha256=")
            ),
            f"qwen_router_admission_transition_sha256={_sha256(transition_path)}",
        )
    )

    with pytest.raises(direct.DirectWorkerError, match="admission_transition_resume_planner_invalid"):
        direct.audit_run_directory(epoch3)


def test_admission_transition_rejects_boolean_schema_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    transition_path = epoch3 / direct.ADMISSION_TRANSITION_FILENAME
    transition = json.loads(transition_path.read_text())
    transition["schema_version"] = True
    transition_path.write_text(json.dumps(transition, sort_keys=True) + "\n")
    provenance_path = epoch3 / "provenance.txt"
    provenance = provenance_path.read_text()
    provenance_path.write_text(
        provenance.replace(
            next(
                line for line in provenance.splitlines() if line.startswith("qwen_router_admission_transition_sha256=")
            ),
            f"qwen_router_admission_transition_sha256={_sha256(transition_path)}",
        )
    )

    with pytest.raises(direct.DirectWorkerError, match="admission_transition_structure_invalid"):
        direct.audit_run_directory(epoch3)


def test_admission_drift_is_rejected_before_worker_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, deployment, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    transition_path = epoch3 / direct.ADMISSION_TRANSITION_FILENAME
    transition_path.write_bytes(transition_path.read_bytes() + b"\n")
    probes = 0

    def forbidden_load(_root: Path):
        nonlocal probes
        probes += 1
        raise AssertionError("worker metadata must not be read after lineage drift")

    monkeypatch.setattr(direct, "load_workers", forbidden_load)
    with pytest.raises(direct.DirectWorkerError, match="provenance_hash_mismatch"):
        direct.prepare(
            deployment,
            epoch3 / "config.toml",
            epoch3 / "direct_workers.json",
            tmp_path / "resume-urls.txt",
            tmp_path / "resume-runtime.txt",
            epoch3 / "inputs" / "task_file.txt",
            _sha256(epoch3 / "inputs" / "task_file.txt"),
            resume=True,
            probe_timeout=1,
        )
    assert probes == 0


def test_admission_migration_refuses_live_or_locked_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    with (epoch2 / ".writer.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(migration.MigrationError, match="source_lock_busy"):
            migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    assert not epoch3.exists()
    with pytest.raises(migration.MigrationError, match="not_terminal"):
        migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: False)
    assert not epoch3.exists()


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        (
            "inference_base_url=http://127.0.0.1:20001/v1",
            "inference_base_url=http://remote.invalid:8100/v1",
            "source_provenance_url_mismatch",
        ),
        (
            "inference_deployment_id=",
            "inference_deployment_id=unexpected",
            "source_provenance_deployment_id_present",
        ),
    ],
)
def test_admission_migration_rejects_unbound_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    error: str,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    provenance = epoch2 / "provenance.txt"
    provenance.write_text(provenance.read_text().replace(old, new))

    with pytest.raises(migration.MigrationError, match=error):
        migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    assert not epoch3.exists()


@pytest.mark.parametrize("mode", ["missing", "hash-drift"])
def test_admission_migration_rejects_invalid_image_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    legacy, _, _, _, _ = _write_source_run(
        tmp_path,
        monkeypatch,
        production=True,
        verifiers_revision=migration.EXPECTED_VERIFIERS_REVISION,
    )
    epoch2 = tmp_path / "epoch2"
    epoch3 = tmp_path / "epoch3"
    migration.migrate(legacy, epoch2, terminal_check=lambda _job_id: True)
    image_snapshot = epoch2 / "inputs" / "image_manifest.json"
    if mode == "missing":
        image_snapshot.unlink()
    else:
        image_snapshot.write_bytes(image_snapshot.read_bytes() + b"drift\n")

    with pytest.raises(migration.MigrationError, match="image_manifest_snapshot_mismatch"):
        migration.migrate_admission(epoch2, epoch3, terminal_check=lambda _job_id: True)
    assert not epoch3.exists()


def test_repository_revision_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(["a" * 40 + "\n", " M workflow.py\n"])

    class Completed:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    monkeypatch.setattr(
        migration.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(next(responses)),
    )

    with pytest.raises(migration.MigrationError, match="migration_repository_not_clean"):
        migration._repository_revision()


def test_pinned_resume_planner_loads_with_isolated_python_path() -> None:
    workflow_dir = Path(__file__).parents[1]
    code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(workflow_dir)!r}); "
        "import migrate_qwen_router_affinity as migration; "
        "module = migration._load_verifiers_resume(migration.EXPECTED_VERIFIERS_REVISION); "
        "print(Path(module.__file__).resolve())"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )

    assert (
        Path(completed.stdout.strip()).resolve()
        == (
            workflow_dir.parents[2] / "deps" / "verifiers" / "verifiers" / "v1" / "cli" / "eval" / "resume.py"
        ).resolve()
    )


def test_resume_planner_compatibility_is_explicit_and_narrow() -> None:
    assert migration.COMPATIBLE_RESUME_VERIFIERS_REVISIONS == {
        migration.EXPECTED_VERIFIERS_REVISION,
        "bb2c42dace0aeecd177e2834f3c87a1d438aed44",
        "fbfbe91d987e0f5bdbcae3eef8c0a272ab9805d5",
        "08a3bf6df2e4f2e04dc1d33e1ee78b7e4da22697",
    }


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


def test_atomic_rename_crash_leaves_marker_that_launchers_reject(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "artifact").write_text("complete\n")
    destination = tmp_path / "destination"

    with pytest.raises(KeyboardInterrupt):
        migration._publish_directory(
            staged,
            destination,
            lambda _path, _allow_incomplete: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    assert not staged.exists()
    marker = destination / direct.MIGRATION_INCOMPLETE_FILENAME
    assert marker.is_file()
    with pytest.raises(direct.DirectWorkerError, match="migration_incomplete"):
        direct.audit_run_directory(destination)


def test_atomic_publication_fsyncs_nested_tree_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = tmp_path / "staged"
    (staged / "inputs").mkdir(parents=True)
    (staged / "inputs" / "artifact").write_text("complete\n")
    destination = tmp_path / "destination"
    events: list[tuple[str, Path]] = []
    real_fsync_tree = migration._fsync_tree

    def record_fsync_tree(path: Path) -> None:
        events.append(("fsync", path))
        real_fsync_tree(path)

    def record_rename(source: Path, target: Path) -> None:
        events.append(("rename", source))
        source.rename(target)

    monkeypatch.setattr(migration, "_fsync_tree", record_fsync_tree)
    monkeypatch.setattr(migration, "_rename_noreplace", record_rename)

    migration._publish_directory(staged, destination, lambda _path, _allow_incomplete: None)

    assert events[:2] == [("fsync", staged), ("rename", staged)]
    assert (destination / "inputs" / "artifact").is_file()
    assert not (destination / direct.MIGRATION_INCOMPLETE_FILENAME).exists()


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
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    index_path = sidecars / "qwen_router_epochs.jsonl"
    source_before = {path.relative_to(child): path.read_bytes() for path in child.rglob("*") if path.is_file()}

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
    source_after = {path.relative_to(child): path.read_bytes() for path in child.rglob("*") if path.is_file()}
    assert source_after == source_before


@pytest.mark.parametrize("tail", [b'{"task":{"idx":1', b"   "])
def test_epoch_index_ignores_attested_malformed_final_fragment_without_mutating_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tail: bytes,
) -> None:
    source, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    migration.migrate(source, child, terminal_check=lambda _job_id: True)
    results = child / "results.jsonl"
    results.write_bytes(results.read_bytes() + tail)
    source_before = results.read_bytes()
    selection, selection_sha256 = _tail_selection(tmp_path, results)

    summary = migration.label_routing_epochs(
        child,
        tmp_path / "qwen_router_epochs.jsonl",
        repair_selection_manifest=selection,
        repair_selection_manifest_sha256=selection_sha256,
        terminal_check=lambda _job_id: True,
    )

    assert summary["ignored_incomplete_tail"] is True
    assert summary["rows"] == 1
    assert summary["results_sha256"] == _sha256(results)
    assert results.read_bytes() == source_before


@pytest.mark.parametrize(
    ("tail", "with_selection", "error_code"),
    [
        (b'{"task":{"idx":1', False, "results_has_incomplete_tail"),
        (b'{"task":\n', True, "results_invalid_complete_row"),
        (b'{"task":\n{"task":{"idx":1}}\n', True, "results_invalid_complete_row"),
    ],
)
def test_epoch_index_rejects_unattested_or_nonfinal_malformed_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tail: bytes,
    with_selection: bool,
    error_code: str,
) -> None:
    source, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    migration.migrate(source, child, terminal_check=lambda _job_id: True)
    results = child / "results.jsonl"
    results.write_bytes(results.read_bytes() + tail)
    selection, selection_sha256 = _tail_selection(tmp_path, results)

    with pytest.raises(migration.MigrationError, match=f"^{error_code}$"):
        migration.label_routing_epochs(
            child,
            tmp_path / "qwen_router_epochs.jsonl",
            repair_selection_manifest=selection if with_selection else None,
            repair_selection_manifest_sha256=selection_sha256 if with_selection else None,
            terminal_check=lambda _job_id: True,
        )


def test_epoch_index_retains_valid_unterminated_final_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _, _, _ = _write_source_run(tmp_path, monkeypatch)
    child = tmp_path / "child"
    migration.migrate(source, child, terminal_check=lambda _job_id: True)
    results = child / "results.jsonl"
    final = json.dumps({"task": {"idx": 1}, "errors": []}, sort_keys=True).encode()
    results.write_bytes(results.read_bytes() + final)

    summary = migration.label_routing_epochs(
        child,
        tmp_path / "qwen_router_epochs.jsonl",
        terminal_check=lambda _job_id: True,
    )

    assert summary["ignored_incomplete_tail"] is False
    assert summary["rows"] == 2


def test_epoch_index_atomic_write_never_replaces_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "qwen_router_epochs.jsonl"
    output.write_bytes(b"keep\n")

    with pytest.raises(migration.MigrationError, match="^epoch_index_output_exists$"):
        migration._atomic_write(output, b"replacement\n", exclusive=True)

    assert output.read_bytes() == b"keep\n"


def test_atomic_write_falls_back_to_hard_link_when_renameat2_is_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output.json"
    monkeypatch.setattr(
        migration,
        "_rename_noreplace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError(errno.EINVAL, "unsupported")),
    )

    migration._atomic_write(output, b"complete\n", exclusive=True)

    assert output.read_bytes() == b"complete\n"
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [output]


def test_atomic_write_hard_link_fallback_has_one_concurrent_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output.json"
    payloads = (b"first-complete\n", b"second-complete\n")
    barrier = threading.Barrier(2)
    original_link = migration.os.link
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def unsupported_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "unsupported")

    def synchronized_link(source: Path, destination: Path, *, follow_symlinks: bool) -> None:
        barrier.wait()
        original_link(source, destination, follow_symlinks=follow_symlinks)

    def write(payload: bytes) -> None:
        try:
            migration._atomic_write(output, payload, exclusive=True)
        except migration.MigrationError as error:
            outcome = str(error)
        else:
            outcome = "success"
        with outcomes_lock:
            outcomes.append(outcome)

    monkeypatch.setattr(migration, "_rename_noreplace", unsupported_rename)
    monkeypatch.setattr(migration.os, "link", synchronized_link)
    writers = [threading.Thread(target=write, args=(payload,)) for payload in payloads]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    assert sorted(outcomes) == ["epoch_index_output_exists", "success"]
    assert output.read_bytes() in payloads
    assert list(tmp_path.iterdir()) == [output]


def test_atomic_write_hard_link_fallback_preserves_existing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output.json"
    output.write_bytes(b"keep\n")
    monkeypatch.setattr(
        migration,
        "_rename_noreplace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError(errno.ENOSYS, "unsupported")),
    )

    with pytest.raises(migration.MigrationError, match="^epoch_index_output_exists$"):
        migration._atomic_write(output, b"replacement\n", exclusive=True)

    assert output.read_bytes() == b"keep\n"
    assert list(tmp_path.iterdir()) == [output]


def test_atomic_write_hard_link_commit_survives_temporary_unlink_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output.json"
    original_unlink = Path.unlink
    retained_temporary: list[Path] = []

    def unsupported_rename(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "unsupported")

    def fail_known_temporary_once(path: Path, *args: object, **kwargs: object) -> None:
        if path.parent == tmp_path and path != output and not retained_temporary:
            retained_temporary.append(path)
            raise OSError(errno.EIO, "injected cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(migration, "_rename_noreplace", unsupported_rename)
    monkeypatch.setattr(Path, "unlink", fail_known_temporary_once)

    migration._atomic_write(output, b"complete\n", exclusive=True)

    assert output.read_bytes() == b"complete\n"
    assert len(retained_temporary) == 1
    assert retained_temporary[0].read_bytes() == b"complete\n"
    assert retained_temporary[0].stat().st_ino == output.stat().st_ino
    original_unlink(retained_temporary[0])


def test_atomic_write_hard_link_fallback_propagates_other_link_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output.json"
    monkeypatch.setattr(
        migration,
        "_rename_noreplace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError(errno.EINVAL, "unsupported")),
    )
    monkeypatch.setattr(
        migration.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EACCES, "denied")),
    )

    with pytest.raises(OSError) as raised:
        migration._atomic_write(output, b"complete\n", exclusive=True)

    assert raised.value.errno == errno.EACCES
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_epoch_index_rejects_output_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(migration.MigrationError, match="^epoch_index_output_overlaps_source$"):
        migration.label_routing_epochs(source, source / "qwen_router_epochs.jsonl")
