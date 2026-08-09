from __future__ import annotations

import json
from pathlib import Path

import audit_defect_withdrawal_training as audit
import pytest
import tomli_w

CONTRACT = audit.AuditContract(
    source_step=0,
    final_step=2,
    group_size=2,
    dataset_rows=4,
    minimum_operation=21,
    maximum_operation=22,
    hard_minimum_operation=21,
    hard_maximum_operation=22,
    endpoints=(
        audit.EndpointContract(1, 1, 1),
        audit.EndpointContract(2, 2, 2),
    ),
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _identity(path: Path) -> dict[str, object]:
    return audit._file_identity(path, path.name)


def _group(group_index: int, task_idx: int, operation: int, cutoff: int) -> dict[str, object]:
    group_id = f"group-{group_index}"
    sample_id = f"sample-{task_idx}"
    return {
        "group_id": group_id,
        "group_index": group_index,
        "env_name": audit.ENVIRONMENT_NAME,
        "task_idx": task_idx,
        "sample_ids": [sample_id, sample_id],
        "operations": [operation, operation],
        "target_size": 2,
        "received_size": 2,
        "advantage_population_size": 2,
        "errored": [False, False],
        "in_advantage_population": [True, True],
        "appended_to_batch": [True, True],
        "metrics": {audit.STRICT_METRIC: [0.0, 1.0]},
        "finalized_before_optimizer_step": cutoff,
    }


def _attempt(batch_attempt: int, optimizer_step: int, group_index: int) -> dict[str, object]:
    return {
        "batch_attempt": batch_attempt,
        "optimizer_step": optimizer_step,
        "eligible_to_ship": True,
        "n_rollouts": 2,
        "n_trainable": 2,
        "group_slices": [{"group_id": f"group-{group_index}", "count": 2, "trainable_count": 2}],
    }


def _fixture(tmp_path: Path) -> Path:
    root = (tmp_path / "run").resolve()
    root.mkdir()
    dataset = tmp_path / "train.jsonl"
    _write_jsonl(
        dataset,
        [
            {"id": "sample-0", "op": 21},
            {"id": "sample-1", "op": 21},
            {"id": "sample-2", "op": 22},
            {"id": "sample-3", "op": 22},
        ],
    )
    dataset_manifest = Path(f"{dataset}.manifest.json")
    dataset_manifest.write_bytes(audit.canonical_json_bytes({"dataset": str(dataset.resolve())}))
    dataset_identity = _identity(dataset)
    training_dataset = {
        "dataset": dataset_identity,
        "adjacent_manifest": _identity(dataset_manifest),
        "manifest_dataset_binding": {
            "path": dataset_identity["path"],
            "sha256": dataset_identity["sha256"],
        },
    }
    fork = {
        "schema_version": 1,
        "artifact_type": audit.FORK_ARTIFACT_TYPE,
        "arm": "p05_off",
        "source_step": 0,
        "final_step": 2,
        "destination": {"root": str(root), "training_dataset": training_dataset},
    }
    fork[audit.SELF_HASH_FIELD] = audit.canonical_json_sha256(fork)
    (root / audit.FORK_MANIFEST_NAME).write_bytes(audit.canonical_json_bytes(fork))
    config = {
        "output_dir": str(root / "run_default"),
        "max_steps": 2,
        "group_size": 2,
        "save_train_group_stats": True,
        "train_source_max_epochs": 1,
        "ckpt": {"resume_step": 0},
        "train": {
            "env": [
                {
                    "name": audit.ENVIRONMENT_NAME,
                    "args": {
                        "dataset_path": str(dataset.resolve()),
                        "false_positive_rate": 0.0,
                        "min_op": 21,
                        "max_op": 22,
                        "require_unique_prompts": True,
                    },
                }
            ]
        },
    }
    config_path = root / "configs" / "orchestrator.toml"
    config_path.parent.mkdir()
    config_path.write_bytes(tomli_w.dumps(config).encode())
    rollout_root = root / "run_default" / "rollouts"
    _write_jsonl(
        rollout_root / "train_group_stats.jsonl",
        [
            _group(1, 0, 21, 0),
            _group(2, 2, 22, 1),
        ],
    )
    _write_jsonl(
        rollout_root / "train_batch_attempts.jsonl",
        [
            _attempt(1, 0, 1),
            _attempt(2, 1, 2),
        ],
    )
    for step in (1, 2):
        checkpoint = root / "weights" / f"step_{step}"
        checkpoint.mkdir(parents=True)
        (checkpoint / "STABLE").touch()
        (checkpoint / "config.json").write_text("{}\n", encoding="utf-8")
    return root


def test_materialized_audit_proves_exact_updates_no_repeat_and_hard_exposure(tmp_path: Path) -> None:
    root = _fixture(tmp_path)

    path = audit.materialize_audit("p05_off", root, contract=CONTRACT)
    result = audit.validate_audit(path, arm="p05_off", run_root=root, contract=CONTRACT)

    assert result["passed"] is True
    assert result["ledger_integrity"]["eligible_shipped_updates"] == 2
    assert result["ledger_integrity"]["no_repeated_task_ids_over_full_continuation"] is True
    assert [row["informative_hard_clean_groups_before_checkpoint"] for row in result["endpoint_audits"]] == [1, 2]
    assert path.stat().st_mode & 0o222 == 0


def test_repeated_task_index_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    groups = root / "run_default" / "rollouts" / "train_group_stats.jsonl"
    rows = [json.loads(line) for line in groups.read_text(encoding="utf-8").splitlines()]
    rows[1]["task_idx"] = 0
    rows[1]["sample_ids"] = ["sample-0", "sample-0"]
    rows[1]["operations"] = [21, 21]
    _write_jsonl(groups, rows)

    with pytest.raises(ValueError, match="repeats continuation task"):
        audit.build_audit("p05_off", root, contract=CONTRACT)


def test_missing_optimizer_update_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    attempts = root / "run_default" / "rollouts" / "train_batch_attempts.jsonl"
    rows = [json.loads(attempts.read_text(encoding="utf-8").splitlines()[0])]
    _write_jsonl(attempts, rows)

    with pytest.raises(ValueError, match="eligible optimizer steps differ"):
        audit.build_audit("p05_off", root, contract=CONTRACT)


def test_off_endpoint_requires_checkpoint_specific_informative_groups(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    groups = root / "run_default" / "rollouts" / "train_group_stats.jsonl"
    rows = [json.loads(line) for line in groups.read_text(encoding="utf-8").splitlines()]
    rows[1]["metrics"][audit.STRICT_METRIC] = [0.0, 0.0]
    _write_jsonl(groups, rows)

    with pytest.raises(ValueError, match="informative hard clean groups"):
        audit.build_audit("p05_off", root, contract=CONTRACT)
