from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "materialize_sandoq_oracle_subset.py"
SPEC = importlib.util.spec_from_file_location("materialize_sandoq_oracle_subset", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
materializer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(materializer)

REGISTRY = "588845226011.dkr.ecr.us-east-2.amazonaws.com/repository"


def _row(dataset: Path, task: str, digest_character: str) -> dict[str, str]:
    context = dataset / task / "environment"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM scratch\n")
    return {
        "task": task,
        "role": "agent",
        "context_sha256": digest_character * 64,
        "context": str(context),
        "image": f"{REGISTRY}:{task}",
    }


def _write_receipt(status: Path, row: dict[str, str], *, success: bool) -> None:
    value: dict[str, object] = {
        **row,
        "state": "success" if success else "failed",
        "cleanup_verified": True,
    }
    if success:
        value["digest"] = "sha256:" + "f" * 64
    else:
        value["failure_stage"] = "image_build"
        value["diagnostic_class"] = "unclassified"
    (status / f"{row['context_sha256']}.agent.json").write_text(json.dumps(value) + "\n")


def test_materialize_strict_noncompose_subset_and_aggregate_receipt(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    status = tmp_path / "status"
    status.mkdir()
    rows = [
        _row(dataset, "complete", "a"),
        _row(dataset, "incomplete", "b"),
        _row(dataset, "compose", "c"),
    ]
    (dataset / "compose" / "environment" / "compose.yaml").write_text("services: {}\n")
    _write_receipt(status, rows[0], success=True)
    _write_receipt(status, rows[1], success=False)
    _write_receipt(status, rows[2], success=True)
    plan = tmp_path / "plan.tsv"
    plan.write_text("".join("\t".join(row.values()) + "\n" for row in rows))
    output = tmp_path / "private" / "tasks.txt"
    manifest = tmp_path / "private" / "manifest.json"
    receipt = tmp_path / "private" / "receipt.json"

    result = materializer.materialize(
        plan_path=plan,
        status_root=status,
        dataset_dir=dataset,
        task_file=output,
        manifest_path=manifest,
        receipt_path=receipt,
        excluded_name_pattern="forbidden",
        dataset_tree_sha256="d" * 64,
        expected_tasks=3,
        expected_plan_rows=3,
        expected_strict_images=2,
        expected_selected=1,
        expected_incomplete=1,
        expected_compose=1,
        minimum_selected=1,
    )

    assert output.read_text() == "complete\n"
    images = json.loads(manifest.read_text())["images"]
    assert list(images) == ["complete"]
    assert images["complete"]["agent"].endswith("@sha256:" + "f" * 64)
    assert result["selected_noncompose_tasks"] == 1
    assert result["incomplete_noncompose_tasks"] == 1
    assert result["compose_tasks_excluded"] == 1
    assert result["incomplete_image_classes"] == {"unclassified": 1}
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert receipt.parent.stat().st_mode & 0o777 == 0o700


def test_materialize_rejects_excluded_boundary_without_outputs(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    status = tmp_path / "status"
    status.mkdir()
    row = _row(dataset, "forbidden-probe", "a")
    _write_receipt(status, row, success=True)
    plan = tmp_path / "plan.tsv"
    plan.write_text("\t".join(row.values()) + "\n")
    task_file = tmp_path / "private" / "tasks.txt"

    with pytest.raises(SystemExit, match="excluded-category boundary"):
        materializer.materialize(
            plan_path=plan,
            status_root=status,
            dataset_dir=dataset,
            task_file=task_file,
            manifest_path=tmp_path / "private" / "manifest.json",
            receipt_path=tmp_path / "private" / "receipt.json",
            excluded_name_pattern="forbidden",
            dataset_tree_sha256="d" * 64,
            expected_tasks=1,
            expected_plan_rows=1,
            expected_strict_images=1,
            expected_selected=1,
            expected_incomplete=0,
            expected_compose=0,
            minimum_selected=1,
        )

    assert not task_file.exists()
