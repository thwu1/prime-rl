from __future__ import annotations

import fcntl
import hashlib
import json
import stat
import tomllib
from pathlib import Path

import direct_qwen_workers as direct
import materialize_qwen_repair as repair
import pytest
from verifiers.v1.cli.eval import resume as resume_planner


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace_assignment(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    indexes = [index for index, line in enumerate(lines) if line.startswith(f"{key} = ")]
    assert len(indexes) == 1
    lines[indexes[0]] = f"{key} = {value}"
    return "\n".join(lines) + "\n"


def _source_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str, dict[Path, bytes]]:
    source = tmp_path / "source"
    inputs = source / "inputs"
    inputs.mkdir(parents=True)
    (source / ".direct_router.lock").write_bytes(b"")
    (source / ".writer.lock").write_bytes(b"")

    identifiers = ("z-completed-scored-zero", "a-error", "m-missing")
    task_bytes = (f"{identifiers[0]}\n{identifiers[1]}\tprivate-source-metadata\n{identifiers[2]}\n").encode()
    task_path = inputs / "task_file.txt"
    task_path.write_bytes(task_bytes)
    task_sha256 = _sha256(task_bytes)

    image_bytes = b"{}\n"
    image_path = inputs / "image_manifest.json"
    image_path.write_bytes(image_bytes)
    image_sha256 = _sha256(image_bytes)

    dataset = tmp_path / "dataset"
    for identifier in identifiers:
        task_dir = dataset / identifier
        task_dir.mkdir(parents=True)
        (task_dir / "task.toml").write_text("[task]\n")
        (task_dir / "instruction.md").write_text("synthetic\n")

    template = repair.CONFIG_TEMPLATE.read_text()
    config_text = _replace_assignment(template, "num_tasks", "3")
    config_text = _replace_assignment(config_text, "task_file", json.dumps(str(task_path)))
    config_text = _replace_assignment(config_text, "task_file_sha256", json.dumps(task_sha256))
    config_text = _replace_assignment(config_text, "image_manifest", json.dumps(str(image_path)))
    config_text = _replace_assignment(config_text, "image_manifest_sha256", json.dumps(image_sha256))
    config_text = _replace_assignment(config_text, "dataset_dir", json.dumps(str(dataset)))
    (source / "config.toml").write_text(config_text)
    (inputs / "source_config.toml").write_text(config_text)
    (inputs / "manifest.json").write_text("{}\n")
    (source / "direct_workers.json").write_text("{}\n")
    (source / "provenance.txt").write_text("slurm_job_id=123\n")

    rows = (
        {
            "task": {"idx": 2, "name": f"suite/{identifiers[0]}"},
            "errors": [],
            "rewards": {"solved": 0},
            "is_completed": True,
            "stop_condition": "synthetic_complete",
        },
        {
            "task": {"idx": 0, "name": f"suite/{identifiers[1]}"},
            "errors": [{"type": "SyntheticError"}],
            "rewards": {},
        },
    )
    (source / "results.jsonl").write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))

    approval = tmp_path / "approved-tasks.txt"
    approval.write_bytes(task_bytes)
    approval_sha256 = _sha256(approval.read_bytes())

    monkeypatch.setattr(
        direct,
        "audit_run_directory",
        lambda _source: {
            "ok": True,
            "model": direct.EXPECTED_MODEL,
            "endpoints": direct.EXPECTED_ENDPOINTS,
            "manifest_schema_version": direct.ROUTER_MANIFEST_SCHEMA_VERSION,
            "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
            "queue_size": direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY,
            "router_policy": direct.ROUTER_POLICY,
            "request_id_headers": list(direct.ROUTER_REQUEST_ID_HEADERS),
            "routing_epoch": 3,
        },
    )
    monkeypatch.setattr(repair, "_load_resume_planner", lambda: resume_planner)
    monkeypatch.setattr(
        repair,
        "_code_provenance",
        lambda: {
            "exporter_sha256": "d" * 64,
            "materializer_sha256": "a" * 64,
            "repository_revision": "b" * 40,
            "submodules": {name: "c" * 40 for name in repair.REQUIRED_RUNTIME_SUBMODULES},
        },
    )
    source_bytes = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    return source, approval, approval_sha256, source_bytes


def test_materialize_uses_sorted_evaluator_indices_for_unsorted_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"

    summary = repair.materialize(
        source,
        approval,
        approval_sha256,
        output,
        terminal_check=lambda _job_id: True,
    )

    assert summary["ok"] is True
    assert summary["missing_or_errored_count"] == 2
    assert summary["approved_repair_count"] == 2
    serialized_summary = json.dumps(summary, sort_keys=True).encode()
    synthetic_identifiers = ("z-completed-scored-zero", "a-error", "m-missing")
    assert all(identifier.encode() not in serialized_summary for identifier in synthetic_identifiers)
    assert (output / repair.TASK_FILENAME).read_text() == "a-error\nm-missing\n"
    for filename in (
        repair.TASK_FILENAME,
        repair.MISSING_ERROR_TASK_FILENAME,
        repair.STRICT_INVALID_PASS_TASK_FILENAME,
        repair.CONFIG_FILENAME,
        repair.MANIFEST_FILENAME,
    ):
        assert stat.S_IMODE((output / filename).stat().st_mode) == 0o600

    config = tomllib.loads((output / repair.CONFIG_FILENAME).read_text())
    assert config["num_tasks"] == 2
    assert config["max_concurrent"] == config["multiplex"] == 64
    assert config["max_input_tokens"] == config["max_output_tokens"] == config["max_total_tokens"] == 262_144
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["max_connections"] == config["client"]["max_keepalive_connections"] == 32
    assert config["sampling"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    assert set(config["retries"]["rollout"]["include"]) == direct.ROLLOUT_RETRY_POLICY

    manifest_bytes = (output / repair.MANIFEST_FILENAME).read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest["planner"]["retained_count"] == 1
    assert manifest["planner"]["missing_or_errored_count"] == 2
    assert manifest["planner"]["task_index_order_sha256"] == summary["task_index_order_sha256"]
    assert manifest["approval"]["approved_task_count"] == 3
    assert manifest["approval"]["approved_task_file_sha256"] == approval_sha256
    assert manifest["code"]["repository_revision"] == "b" * 40
    assert set(manifest["code"]["submodules"]) == set(repair.REQUIRED_RUNTIME_SUBMODULES)
    assert manifest["selection"]["approved_repair_count"] == 2
    assert manifest["selection"]["missing_or_errored_count"] == 2
    assert manifest["selection"]["strict_invalid_pass_count"] == 0
    assert summary["strict_invalid_pass_count"] == 0
    for identifier in synthetic_identifiers:
        assert identifier.encode() not in manifest_bytes
    assert b"private-source-metadata" not in manifest_bytes
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()} == source_bytes


def test_materialize_unions_missing_error_with_multiple_name_only_invalid_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, _approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    identifiers = ("d-fail", "b-invalid-reasoning", "e-missing", "a-error", "c-invalid-model-io")
    task_body = "".join(f"{identifier}\n" for identifier in identifiers).encode()
    approval.write_bytes(task_body)
    (source / "inputs" / "task_file.txt").write_bytes(task_body)
    dataset = Path(tomllib.loads((source / "config.toml").read_text())["taskset"]["dataset_dir"])
    for identifier in identifiers:
        task_dir = dataset / identifier
        task_dir.mkdir(exist_ok=True)
        (task_dir / "task.toml").write_text("[task]\n")
        (task_dir / "instruction.md").write_text("synthetic\n")
    config = (source / "config.toml").read_text()
    config = _replace_assignment(config, "num_tasks", "5")
    config = _replace_assignment(config, "task_file_sha256", json.dumps(_sha256(task_body)))
    (source / "config.toml").write_text(config)
    ordered = sorted(identifiers)
    rows = [
        {
            "task": {"idx": 0, "name": f"suite/{ordered[0]}"},
            "errors": [{"type": "SyntheticError"}],
            "rewards": {},
        },
        {
            "task": {"idx": 1, "name": f"suite/{ordered[1]}"},
            "errors": [],
            "rewards": {"solved": 1},
            "is_completed": True,
            "stop_condition": "synthetic_complete",
            "nodes": [],
        },
        {
            "task": {"idx": 2, "name": f"suite/{ordered[2]}"},
            "errors": [],
            "rewards": {"solved": 1},
            "is_completed": True,
            "stop_condition": "synthetic_complete",
            "nodes": [{"sampled": True}],
        },
        {
            "task": {"idx": 3, "name": f"suite/{ordered[3]}"},
            "errors": [],
            "rewards": {"solved": 0},
            "is_completed": True,
            "stop_condition": "synthetic_complete",
        },
    ]
    (source / "results.jsonl").write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))
    source_before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}

    summary = repair.materialize(
        source,
        approval,
        _sha256(task_body),
        tmp_path / "repair-union",
        terminal_check=lambda _job_id: True,
    )

    assert summary["approved_repair_count"] == 4
    assert summary["missing_or_errored_count"] == 2
    assert summary["strict_invalid_pass_count"] == 2
    output = tmp_path / "repair-union"
    assert (
        output / repair.TASK_FILENAME
    ).read_text() == "a-error\nb-invalid-reasoning\nc-invalid-model-io\ne-missing\n"
    assert (output / repair.MISSING_ERROR_TASK_FILENAME).read_text() == "a-error\ne-missing\n"
    assert (output / repair.STRICT_INVALID_PASS_TASK_FILENAME).read_text() == (
        "b-invalid-reasoning\nc-invalid-model-io\n"
    )
    manifest = json.loads((output / repair.MANIFEST_FILENAME).read_bytes())
    assert manifest["selection"]["approved_repair_count"] == 4
    assert manifest["selection"]["missing_or_errored_count"] == 2
    assert manifest["selection"]["strict_invalid_pass_count"] == 2
    serialized = json.dumps(summary, sort_keys=True) + json.dumps(manifest, sort_keys=True)
    assert all(identifier not in serialized for identifier in identifiers)
    assert {
        path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()
    } == source_before


def test_materialize_rejects_invalid_name_even_when_slug_is_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in (source / "results.jsonl").read_text().splitlines()]
    rows[0]["task"]["slug"] = rows[0]["task"]["name"].rsplit("/", 1)[-1]
    rows[0]["task"]["name"] = None
    (source / "results.jsonl").write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))

    with pytest.raises(repair.RepairMaterializationError, match="^source_results_identity_invalid$"):
        repair.materialize(
            source,
            approval,
            approval_sha256,
            tmp_path / "repair-invalid-name",
            terminal_check=lambda _job_id: True,
        )


def test_materialize_rejects_slug_only_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in (source / "results.jsonl").read_text().splitlines()]
    name = rows[0]["task"].pop("name")
    rows[0]["task"]["slug"] = name.rsplit("/", 1)[-1]
    (source / "results.jsonl").write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))

    with pytest.raises(repair.RepairMaterializationError, match="^source_results_identity_invalid$"):
        repair.materialize(
            source,
            approval,
            approval_sha256,
            tmp_path / "repair-slug-only",
            terminal_check=lambda _job_id: True,
        )


@pytest.mark.parametrize("tail", [b'{"task":{"idx":1', b"   "])
def test_materialize_ignores_only_malformed_unterminated_final_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tail: bytes,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    results = source / "results.jsonl"
    results.write_bytes(results.read_bytes() + tail)
    source_results = results.read_bytes()

    summary = repair.materialize(
        source,
        approval,
        approval_sha256,
        tmp_path / "repair-truncated-tail",
        terminal_check=lambda _job_id: True,
    )

    assert summary["missing_or_errored_count"] == 2
    assert summary["approved_repair_count"] == 2
    manifest = json.loads((tmp_path / "repair-truncated-tail" / repair.MANIFEST_FILENAME).read_text())
    assert manifest["source"]["artifacts"]["results"] == {
        "sha256": hashlib.sha256(source_results).hexdigest(),
        "size_bytes": len(source_results),
    }
    assert results.read_bytes() == source_results


@pytest.mark.parametrize(
    "body",
    [
        b'{"task":\n',
        b'{"task":\n{"task":{"idx":1}}\n',
    ],
)
def test_materialize_rejects_malformed_complete_or_interior_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    results = source / "results.jsonl"
    results.write_bytes(results.read_bytes() + body)

    with pytest.raises(repair.RepairMaterializationError, match="^resume_plan_failed$"):
        repair.materialize(
            source,
            approval,
            approval_sha256,
            tmp_path / "repair-malformed-row",
            terminal_check=lambda _job_id: True,
        )


def test_materialize_keeps_valid_unterminated_final_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    final = {
        "task": {"idx": 1, "name": "suite/m-missing"},
        "errors": [],
        "rewards": {"solved": 0},
        "is_completed": True,
        "stop_condition": "synthetic_complete",
    }
    results = source / "results.jsonl"
    results.write_bytes(results.read_bytes() + json.dumps(final, sort_keys=True).encode())
    source_results = results.read_bytes()

    summary = repair.materialize(
        source,
        approval,
        approval_sha256,
        tmp_path / "repair-valid-tail",
        terminal_check=lambda _job_id: True,
    )

    assert summary["missing_or_errored_count"] == 1
    assert summary["approved_repair_count"] == 1
    assert results.read_bytes() == source_results


@pytest.mark.parametrize("lock_name", [".writer.lock", ".direct_router.lock"])
def test_materialize_rejects_busy_source_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lock_name: str,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"

    with (source / lock_name).open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(repair.RepairMaterializationError, match="source_lock_busy"):
            repair.materialize(
                source,
                approval,
                approval_sha256,
                output,
                terminal_check=lambda _job_id: True,
            )
    assert not output.exists()


def test_materialize_rejects_approval_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, _approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"

    with pytest.raises(repair.RepairMaterializationError, match="approval_sha256_mismatch"):
        repair.materialize(
            source,
            approval,
            "0" * 64,
            output,
            terminal_check=lambda _job_id: True,
        )
    assert not output.exists()


def test_materialize_rejects_nonterminal_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"

    with pytest.raises(repair.RepairMaterializationError, match="source_job_not_terminal"):
        repair.materialize(
            source,
            approval,
            approval_sha256,
            output,
            terminal_check=lambda _job_id: False,
        )
    assert not output.exists()


def test_materialize_rejects_approval_that_is_not_exact_source_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, _approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    approval.write_text("not-in-source\n")
    output = tmp_path / "repair"

    with pytest.raises(repair.RepairMaterializationError, match="approval_source_mismatch"):
        repair.materialize(
            source,
            approval,
            _sha256(approval.read_bytes()),
            output,
            terminal_check=lambda _job_id: True,
        )
    assert not output.exists()


def test_materialize_rejects_invalid_planner_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"

    class InvalidPlanner:
        @staticmethod
        def plan(*_args, **_kwargs):
            return [], {1: 2}

    monkeypatch.setattr(repair, "_load_resume_planner", lambda: InvalidPlanner)
    with pytest.raises(repair.RepairMaterializationError, match="resume_plan_invalid"):
        repair.materialize(
            source,
            approval,
            approval_sha256,
            output,
            terminal_check=lambda _job_id: True,
        )
    assert not output.exists()


def test_materialize_reports_zero_owed_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"
    ordered = ("a-error", "m-missing", "z-completed-scored-zero")
    (source / "results.jsonl").write_bytes(
        b"".join(
            (
                json.dumps(
                    {
                        "task": {"idx": index, "name": f"suite/{slug}"},
                        "errors": [],
                        "rewards": {"solved": 0},
                        "is_completed": True,
                        "stop_condition": "synthetic_complete",
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode()
            for index, slug in enumerate(ordered)
        )
    )

    class CompletePlanner:
        @staticmethod
        def plan(*_args, **_kwargs):
            return [0, 1, 2], {}

    monkeypatch.setattr(repair, "_load_resume_planner", lambda: CompletePlanner)
    summary = repair.materialize(
        source,
        approval,
        approval_sha256,
        output,
        terminal_check=lambda _job_id: True,
    )

    assert summary["approved_repair_count"] == 0
    assert summary["approved_task_file_sha256"] == approval_sha256
    assert summary["missing_or_errored_count"] == 0
    assert summary["ok"] is True
    assert summary["status"] == "nothing_to_repair"
    assert len(summary["task_index_order_sha256"]) == 64
    assert not output.exists()


def test_materialize_does_not_overwrite_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    output = tmp_path / "repair"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("keep\n")

    with pytest.raises(repair.RepairMaterializationError, match="destination_exists"):
        repair.materialize(
            source,
            approval,
            approval_sha256,
            output,
            terminal_check=lambda _job_id: True,
        )
    assert sentinel.read_text() == "keep\n"
