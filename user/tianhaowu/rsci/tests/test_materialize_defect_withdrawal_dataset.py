from __future__ import annotations

import hashlib
import json
from pathlib import Path

import orjson
import pytest
import torch
from materialize_defect_withdrawal_dataset import (
    SELF_HASH_FIELD,
    MaterializationSpec,
    SourceSpec,
    _scan_original_dataset,
    _select_rows,
    canonical_json_sha256,
    materialize_dataset,
    validate_materialized_dataset,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_dataset(root: Path) -> tuple[Path, list[dict]]:
    root.mkdir(parents=True)
    rows = []
    for operation in (10, 11):
        for item in range(4):
            rows.append(
                {
                    "id": f"op{operation}-item{item}",
                    "op": operation,
                    "prompt": f"prompt for op {operation} item {item}",
                    "answer": str(operation + item),
                    "template": "movie_festival_awards" if item < 2 else "teachers_in_school",
                    "mode": "normalforward" if item < 2 else "forwardreverse",
                    "extra": {"preserved": True, "item": item},
                }
            )
    dataset_path = root / "train.jsonl"
    dataset_path.write_bytes(b"".join(orjson.dumps(row) + b"\n" for row in rows))
    identity = {"path": str(dataset_path.resolve()), "rows": len(rows), "sha256": _sha256(dataset_path)}
    (root / "dataset_manifest.json").write_text(
        json.dumps({"files": {"train": identity}}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "audit.json").write_text(
        json.dumps(
            {
                "train": {
                    **identity,
                    "unique_ids": len(rows),
                    "unique_prompts": len(rows),
                    "by_op": {"10": 4, "11": 4},
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return dataset_path, rows


def _rollout_row(index: int, dataset_rows: list[dict], rollout_id: str) -> dict:
    source = dataset_rows[index]
    return {
        "id": rollout_id,
        "is_completed": True,
        "errors": [],
        "task": {"idx": index, "prompt": source["prompt"], "answer": source["answer"]},
        "rewards": {"reward": 0},
    }


def _write_source(root: Path, label: str, dataset_rows: list[dict], step_indices: list[list[int]]) -> SourceSpec:
    total_samples = 0
    total_problems = 0
    for step, indices in enumerate(step_indices):
        path = root / "run_default/rollouts" / f"step_{step}" / "train_rollouts.jsonl"
        path.parent.mkdir(parents=True)
        rows = [
            _rollout_row(index, dataset_rows, f"{label}-{step}-{position}") for position, index in enumerate(indices)
        ]
        path.write_bytes(b"".join(orjson.dumps(row) + b"\n" for row in rows))
        total_samples += len(rows)
        total_problems += len(set(indices))
    progress_path = root / "run_default/checkpoints" / f"step_{len(step_indices)}" / "orchestrator/progress.pt"
    progress_path.parent.mkdir(parents=True)
    torch.save(
        {
            "progress": {
                "step": len(step_indices),
                "total_tokens": 123,
                "total_samples": total_samples,
                "total_problems": total_problems,
            }
        },
        progress_path,
    )
    return SourceSpec(
        label=label,
        root=root,
        expected_total_samples=total_samples,
        expected_total_problems=total_problems,
    )


@pytest.fixture
def withdrawal_fixture(tmp_path: Path) -> tuple[MaterializationSpec, list[dict]]:
    dataset_root = tmp_path / "dataset"
    dataset_path, dataset_rows = _write_dataset(dataset_root)
    p00 = _write_source(tmp_path / "p00", "p00", dataset_rows, [[0, 0], [0, 2]])
    p05 = _write_source(tmp_path / "p05", "p05", dataset_rows, [[4, 4], [4, 6]])
    output_path = tmp_path / "output/train.jsonl"
    spec = MaterializationSpec(
        dataset_path=dataset_path,
        dataset_manifest_path=dataset_root / "dataset_manifest.json",
        audit_path=dataset_root / "audit.json",
        output_path=output_path,
        sources=(p00, p05),
        step_count=2,
        progress_step=2,
        min_operation=10,
        max_operation=11,
        quota_per_operation=2,
        strata=(("movie_festival_awards", "normalforward"), ("teachers_in_school", "forwardreverse")),
        minimum_task_pull_capacity=3,
        expected_excluded_indices_sha256=None,
        expected_source_overlap_sha256=None,
        expected_selected_indices_sha256=None,
        expected_available_rows_total=None,
        implementation_path=Path(__file__).parents[1] / "materialize_defect_withdrawal_dataset.py",
    )
    return spec, dataset_rows


def test_materializes_balanced_byte_identical_unseen_rows(
    withdrawal_fixture: tuple[MaterializationSpec, list[dict]],
) -> None:
    spec, dataset_rows = withdrawal_fixture
    manifest_path = materialize_dataset(spec)
    manifest = validate_materialized_dataset(manifest_path, expected_spec=spec)

    expected = b"".join(orjson.dumps(dataset_rows[index]) + b"\n" for index in (1, 3, 5, 7))
    assert spec.output_path.read_bytes() == expected
    assert manifest["selection"]["available_rows_by_operation"] == {"10": 2, "11": 2}
    assert manifest["selection"]["selected_rows_by_operation"] == {"10": 2, "11": 2}
    assert manifest["selection"]["headroom_over_minimum_task_pull_capacity"] == 1
    assert manifest["exclusions"]["unique_indices"] == 4
    assert manifest["output"]["rows"] == 4
    p00_rollouts = manifest["sources"][0]["shipped_rollout_files"]
    assert p00_rollouts["sum_per_step_unique_task_indices"] == 3
    assert p00_rollouts["union_unique_task_indices"] == 2
    all_unseen_selected, _ = _select_rows(spec, _scan_original_dataset(spec).rows, set())
    assert all_unseen_selected == {1, 3, 5, 6}


def test_validation_replays_rollout_sources(
    withdrawal_fixture: tuple[MaterializationSpec, list[dict]],
) -> None:
    spec, _ = withdrawal_fixture
    manifest_path = materialize_dataset(spec)
    rollout_path = spec.sources[0].root / "run_default/rollouts/step_0/train_rollouts.jsonl"
    rows = [orjson.loads(line) for line in rollout_path.read_bytes().splitlines()]
    rows[0]["rewards"]["reward"] = 1
    rollout_path.write_bytes(b"".join(orjson.dumps(row) + b"\n" for row in rows))

    with pytest.raises(ValueError, match="Manifest evidence does not match"):
        validate_materialized_dataset(manifest_path, expected_spec=spec)


def test_validation_rejects_self_rehashed_contract_change(
    withdrawal_fixture: tuple[MaterializationSpec, list[dict]],
) -> None:
    spec, _ = withdrawal_fixture
    manifest_path = materialize_dataset(spec)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parameters"]["strata"][0]["mode"] = "changed-mode"
    manifest.pop(SELF_HASH_FIELD)
    manifest[SELF_HASH_FIELD] = canonical_json_sha256(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest materialization contract"):
        validate_materialized_dataset(manifest_path, expected_spec=spec)
