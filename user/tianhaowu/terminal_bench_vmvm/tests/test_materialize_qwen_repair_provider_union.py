from __future__ import annotations

import hashlib
import json
from pathlib import Path

import finalize_qwen_repair_sft as repair_finalizer
import materialize_qwen_provider_union as full_union
import materialize_qwen_repair_provider_union as repair_union
import pytest
from audit_traces import qwen_repair_trace_contracts_value


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _task(root: Path, name: str, *, compose: bool = False) -> None:
    task = root / name
    (task / "environment").mkdir(parents=True)
    (task / "task.toml").write_text('[environment]\nnetwork_mode = "no-network"\n')
    if compose:
        (task / "environment" / "compose.yaml").write_text("services = {}\n")


def _selection(tmp_path: Path, members: tuple[str, ...]) -> repair_finalizer.RepairSelection:
    body = "".join(f"{member}\n" for member in members).encode()
    manifest = tmp_path / "selection" / "repair_manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}\n")
    manifest.chmod(0o600)
    return repair_finalizer.RepairSelection(
        body=manifest.read_bytes(),
        sha256=_sha(manifest.read_bytes()),
        selection_bodies={repair_finalizer.SELECTION_TASK_COPY_FILENAME: body},
        selection_artifacts={},
        selection_paths={},
        config_sha256="1" * 64,
        task_file_sha256=_sha(body),
        repair_union_indices_sha256="2" * 64,
        task_count=len(members),
        missing_or_errored_count=len(members),
        strict_invalid_pass_count=0,
        approved_task_count=4,
        template_sha256="3" * 64,
        materializer_sha256="4" * 64,
        exporter_sha256="5" * 64,
        repository_revision="6" * 40,
        source_artifacts={},
        source_partition={},
        submodules={},
        trace_contracts=qwen_repair_trace_contracts_value(),
    )


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    members: tuple[str, ...],
) -> dict[str, Path | str]:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    canonical = ("opaque-a", "opaque-b", "opaque-c", "opaque-d")
    for member in canonical[:-1]:
        _task(dataset, member)
    _task(dataset, canonical[-1], compose=True)
    source = tmp_path / "canonical.txt"
    source.write_text("".join(f"{member}\n" for member in canonical))
    template_body = (
        "num_tasks = 2500\n"
        "max_concurrent = 64\n"
        "multiplex = 64\n"
        "max_connections = 32\n"
        "max_keepalive_connections = 32\n"
        "[sampling]\n"
        'reasoning_effort = "high"\n'
        "[taskset]\n"
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"\n'
        f'task_file_sha256 = "{_sha(source.read_bytes())}"\n'
    )
    sandoq_template = tmp_path / "sandoq.toml"
    vmvm_template = tmp_path / "vmvm.toml"
    sandoq_template.write_text(template_body)
    vmvm_template.write_text(template_body + "enable_compose = true\n")
    selection = _selection(tmp_path, members)
    output = tmp_path / full_union.DEPLOYMENT_NAMESPACE
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    historical_source = tmp_path / "historical-source"
    historical_source.mkdir()
    for name in (".writer.lock", ".direct_router.lock"):
        lock = historical_source / name
        lock.touch()
        lock.chmod(0o600)

    monkeypatch.setattr(full_union, "CANONICAL_SOURCE_COUNT", len(canonical))
    monkeypatch.setattr(full_union, "SANDOQ_COUNT", len(canonical) - 1)
    monkeypatch.setattr(full_union, "CANONICAL_SOURCE_SHA256", _sha(source.read_bytes()))
    monkeypatch.setattr(full_union, "CANONICAL_SANDOQ_TEMPLATE_SHA256", _sha(sandoq_template.read_bytes()))
    monkeypatch.setattr(full_union, "CANONICAL_VMVM_TEMPLATE_SHA256", _sha(vmvm_template.read_bytes()))
    monkeypatch.setattr(repair_union, "CANONICAL_SOURCE_COUNT", len(canonical))
    monkeypatch.setattr(repair_union, "CANONICAL_SOURCE_SHA256", _sha(source.read_bytes()))
    monkeypatch.setattr(repair_union, "verify_canonical_dataset", lambda path: path.resolve(strict=True))
    monkeypatch.setattr(repair_union, "_load_selection", lambda *_args: (selection, members))
    monkeypatch.setattr(repair_union, "_validate_selection_source_and_code", lambda *_args: None)

    return {
        "source": source,
        "dataset": dataset,
        "sandoq_template": sandoq_template,
        "vmvm_template": vmvm_template,
        "repair_selection_manifest": tmp_path / "selection" / "repair_manifest.json",
        "repair_selection_manifest_sha256": selection.sha256,
        "historical_source_dir": historical_source,
        "sandoq_tasks": output / "repair_sandoq_tasks.txt",
        "vmvm_tasks": output / "repair_vmvm_tasks.txt",
        "sandoq_config": output / "repair_sandoq_config.toml",
        "vmvm_config": output / "repair_vmvm_config.toml",
        "receipt": output / "repair_provider_receipt.json",
        "private_output_root": output,
    }


@pytest.mark.parametrize(
    ("members", "expected_sandoq_members", "expected_vmvm_members"),
    [
        (("opaque-a", "opaque-b"), ("opaque-a", "opaque-b"), ()),
    ],
)
def test_materializes_exact_repair_intersection_without_full_corpus_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    members: tuple[str, ...],
    expected_sandoq_members: tuple[str, ...],
    expected_vmvm_members: tuple[str, ...],
) -> None:
    paths = _inputs(tmp_path, monkeypatch, members)
    expected_sandoq = len(expected_sandoq_members)
    expected_vmvm = len(expected_vmvm_members)

    summary = repair_union.materialize(**paths)

    assert summary == {
        "state": "materialized",
        "repair_count": 2,
        "sandoq_count": expected_sandoq,
        "vmvm_count": expected_vmvm,
    }
    receipt = json.loads(Path(paths["receipt"]).read_bytes())
    assert receipt["partition"] == {
        "disjoint": True,
        "exhaustive": True,
        "sandoq_count": expected_sandoq,
        "vmvm_count": expected_vmvm,
        "total_count": 2,
    }
    assert Path(paths["sandoq_tasks"]).read_text().splitlines() == list(expected_sandoq_members)
    assert Path(paths["vmvm_tasks"]).read_text().splitlines() == list(expected_vmvm_members)
    encoded_receipt = json.dumps(receipt, sort_keys=True)
    assert all(member not in encoded_receipt for member in members)
    assert "sandoq_tasks" not in encoded_receipt
    assert "vmvm_tasks" not in encoded_receipt
    assert Path(paths["vmvm_tasks"]).read_bytes() == b""
    assert "num_tasks = 0" in Path(paths["vmvm_config"]).read_text()
    assert "max_concurrent = 0" in Path(paths["vmvm_config"]).read_text()
    validated = repair_union.validate_materialization(
        **paths,
        receipt_sha256=_sha(Path(paths["receipt"]).read_bytes()),
    )
    assert validated["partition"]["total_count"] == 2


def test_repair_intersection_rejects_noncanonical_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _inputs(tmp_path, monkeypatch, ("opaque-a", "opaque-unknown"))

    with pytest.raises(
        repair_union.RepairProviderMaterializationError,
        match="^repair_selection_not_canonical_subset$",
    ):
        repair_union.materialize(**paths)


def test_repair_intersection_requires_certified_empty_vmvm_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _inputs(tmp_path, monkeypatch, ("opaque-a", "opaque-d"))

    with pytest.raises(
        repair_union.RepairProviderMaterializationError,
        match="^repair_provider_partition_invalid$",
    ):
        repair_union.materialize(**paths)


def test_materialization_rejects_selection_change_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _inputs(tmp_path, monkeypatch, ("opaque-a", "opaque-b"))

    def changed(_selection) -> None:
        raise repair_finalizer.RepairFinalizationError("repair_selection_changed")

    monkeypatch.setattr(repair_finalizer, "_validate_selection_unchanged", changed)
    with pytest.raises(
        repair_union.RepairProviderMaterializationError,
        match="^repair_selection_changed$",
    ):
        repair_union.materialize(**paths)

    assert not Path(paths["receipt"]).exists()
