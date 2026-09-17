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

    identifiers = ("completed-scored-zero", "approved-error", "outside-approval-missing")
    task_bytes = (f"{identifiers[0]}\n{identifiers[1]}\tprivate-source-metadata\n{identifiers[2]}\n").encode()
    task_path = inputs / "task_file.txt"
    task_path.write_bytes(task_bytes)
    task_sha256 = _sha256(task_bytes)

    image_bytes = b"{}\n"
    image_path = inputs / "image_manifest.json"
    image_path.write_bytes(image_bytes)
    image_sha256 = _sha256(image_bytes)

    template = repair.CONFIG_TEMPLATE.read_text()
    config_text = _replace_assignment(template, "num_tasks", "3")
    config_text = _replace_assignment(config_text, "task_file", json.dumps(str(task_path)))
    config_text = _replace_assignment(config_text, "task_file_sha256", json.dumps(task_sha256))
    config_text = _replace_assignment(config_text, "image_manifest", json.dumps(str(image_path)))
    config_text = _replace_assignment(config_text, "image_manifest_sha256", json.dumps(image_sha256))
    (source / "config.toml").write_text(config_text)
    (inputs / "source_config.toml").write_text(config_text)
    (inputs / "manifest.json").write_text("{}\n")
    (source / "direct_workers.json").write_text("{}\n")
    (source / "provenance.txt").write_text("slurm_job_id=123\n")

    rows = (
        {"task": {"idx": 0}, "errors": [], "rewards": {"solved": 0}},
        {"task": {"idx": 1}, "errors": [{"type": "SyntheticError"}], "rewards": {}},
    )
    (source / "results.jsonl").write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))

    approval = tmp_path / "approved-non-security.txt"
    approval.write_text(f"{identifiers[0]}\n{identifiers[1]}\tapproval-metadata\n")
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
    source_bytes = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    return source, approval, approval_sha256, source_bytes


def test_materialize_selects_only_approved_missing_or_errored_tasks(
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
    assert summary["approved_repair_count"] == 1
    assert summary["excluded_outside_approval_count"] == 1
    serialized_summary = json.dumps(summary, sort_keys=True).encode()
    assert all(
        identifier.encode() not in serialized_summary for identifier in ("completed-scored-zero", "approved-error")
    )
    assert (output / repair.TASK_FILENAME).read_text() == "approved-error\n"
    for filename in (repair.TASK_FILENAME, repair.CONFIG_FILENAME, repair.MANIFEST_FILENAME):
        assert stat.S_IMODE((output / filename).stat().st_mode) == 0o600

    config = tomllib.loads((output / repair.CONFIG_FILENAME).read_text())
    assert config["num_tasks"] == 1
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
    assert manifest["approval"]["non_security_universe_count"] == 2
    assert manifest["selection"]["approved_repair_count"] == 1
    assert manifest["selection"]["excluded_outside_approval_count"] == 1
    for identifier in ("completed-scored-zero", "approved-error", "outside-approval-missing"):
        assert identifier.encode() not in manifest_bytes
    assert b"private-source-metadata" not in manifest_bytes
    assert b"approval-metadata" not in manifest_bytes
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()} == source_bytes


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


def test_materialize_rejects_approval_outside_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, approval, _approval_sha256, _source_bytes = _source_run(tmp_path, monkeypatch)
    approval.write_text("not-in-source\n")
    output = tmp_path / "repair"

    with pytest.raises(repair.RepairMaterializationError, match="approval_outside_source"):
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
