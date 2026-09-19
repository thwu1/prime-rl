from __future__ import annotations

import hashlib
import json
from pathlib import Path

import materialize_qwen_provider_union as union
import pytest


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _task(root: Path, name: str, *, compose: bool = False, public: bool = False) -> None:
    task = root / name
    (task / "environment").mkdir(parents=True)
    mode = "public" if public else "no-network"
    (task / "task.toml").write_text(f'[environment]\nnetwork_mode = "{mode}"\n')
    if compose:
        (task / "environment" / "compose.yaml").write_text("services = {}\n")


def _templates(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    common = (
        "num_tasks = 2500\n"
        "max_concurrent = 64\n"
        "multiplex = 64\n"
        "max_connections = 32\n"
        "max_keepalive_connections = 32\n"
        "[sampling]\n"
        "[taskset]\n"
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/'
        'mobius_valid_tasks_2500.txt"\n'
        f'task_file_sha256 = "{union.CANONICAL_SOURCE_SHA256}"\n'
    )
    sandoq = tmp_path / "sandoq.toml"
    vmvm = tmp_path / "vmvm.toml"
    sandoq.write_text(common + 'reasoning_effort = "max"\n')
    vmvm.write_text(common)
    monkeypatch.setattr(union, "CANONICAL_SANDOQ_TEMPLATE_SHA256", _sha(sandoq.read_bytes()))
    monkeypatch.setattr(union, "CANONICAL_VMVM_TEMPLATE_SHA256", _sha(vmvm.read_bytes()))
    return sandoq, vmvm


def _inputs(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    members = ("opaque-a", "opaque-b", "opaque-c", "opaque-d")
    for member in members[:-1]:
        _task(dataset, member)
    _task(dataset, members[-1], compose=True)
    source = tmp_path / "source.txt"
    source.write_text("".join(f"{member}\n" for member in members))
    monkeypatch.setattr(union, "CANONICAL_SOURCE_COUNT", 4)
    monkeypatch.setattr(union, "SANDOQ_COUNT", 3)
    monkeypatch.setattr(union, "CANONICAL_SOURCE_SHA256", _sha(source.read_bytes()))
    monkeypatch.setattr(union, "verify_canonical_dataset", lambda path: path.resolve(strict=True))
    sandoq_template, vmvm_template = _templates(tmp_path, monkeypatch)
    return {
        "source": source,
        "dataset": dataset,
        "sandoq_template": sandoq_template,
        "vmvm_template": vmvm_template,
        "sandoq_tasks": tmp_path / "out" / "sandoq.txt",
        "vmvm_tasks": tmp_path / "out" / "vmvm.txt",
        "sandoq_config": tmp_path / "out" / "sandoq.toml",
        "vmvm_config": tmp_path / "out" / "vmvm.toml",
        "receipt": tmp_path / "out" / "receipt.json",
    }


def test_materializes_private_disjoint_exhaustive_partition(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)

    result = union.materialize(**paths)

    assert result == {"state": "materialized", "source_count": 4, "sandoq_count": 3, "vmvm_count": 1}
    receipt_raw = paths["receipt"].read_bytes()
    receipt = json.loads(receipt_raw)
    assert receipt["partition"] == {
        "compose_count": 1,
        "disjoint": True,
        "exhaustive": True,
        "no_network_count": 4,
        "sandoq_count": 3,
        "vmvm_count": 1,
    }
    # Neither member names nor hashes of the one-member private file are public.
    assert all(member.encode() not in receipt_raw for member in ("opaque-a", "opaque-b", "opaque-c", "opaque-d"))
    assert _sha(paths["vmvm_tasks"].read_bytes()).encode() not in receipt_raw
    validation = union.validate_materialization(
        **paths,
        receipt_sha256=_sha(receipt_raw),
    )
    assert validation["partition"]["sandoq_count"] == 3
    assert validation["partition"]["vmvm_count"] == 1
    assert 'enable_compose = true' in paths["vmvm_config"].read_text()
    assert 'reasoning_effort = "max"' in paths["vmvm_config"].read_text()


def test_validation_rejects_partition_overlap_or_omission(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    union.materialize(**paths)
    paths["sandoq_tasks"].write_bytes(paths["sandoq_tasks"].read_bytes() + paths["vmvm_tasks"].read_bytes())

    with pytest.raises(union.MixedMaterializationError, match="^materialized_partition_mismatch$"):
        union.validate_materialization(
            **paths,
            receipt_sha256=_sha(paths["receipt"].read_bytes()),
        )


def test_partition_rejects_second_compose_member(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    (paths["dataset"] / "opaque-a" / "environment" / "compose.yml").write_text("services = {}\n")

    with pytest.raises(union.MixedMaterializationError, match="^canonical_partition_cardinality_mismatch$"):
        union.materialize(**paths)


def test_partition_rejects_public_network_member(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    (paths["dataset"] / "opaque-a" / "task.toml").write_text(
        '[environment]\nnetwork_mode = "public"\n'
    )

    with pytest.raises(union.MixedMaterializationError, match="^task_network_not_isolated$"):
        union.materialize(**paths)


def test_partition_rejects_symlinked_compose_artifact(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    compose = paths["dataset"] / "opaque-d" / "environment" / "compose.yaml"
    body = compose.read_bytes()
    compose.unlink()
    target = tmp_path / "outside-compose"
    target.write_bytes(body)
    compose.symlink_to(target)

    with pytest.raises(union.MixedMaterializationError, match="^compose_artifact_invalid$"):
        union.materialize(**paths)


def test_publish_is_fail_closed_on_existing_output(tmp_path: Path, monkeypatch) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    paths["sandoq_tasks"].parent.mkdir()
    paths["receipt"].write_text("preexisting\n")

    with pytest.raises(union.MixedMaterializationError, match="^outputs_require_fresh_namespace$"):
        union.materialize(**paths)
    assert paths["receipt"].read_text() == "preexisting\n"
    assert not paths["sandoq_tasks"].exists()
