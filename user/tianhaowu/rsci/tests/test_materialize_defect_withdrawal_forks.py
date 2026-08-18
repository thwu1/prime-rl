from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import tomli_w
import torch
from materialize_defect_withdrawal_forks import (
    CHECKPOINT_INTERVAL,
    DESTINATION_KEEP_INTERVAL,
    DESTINATION_KEEP_LAST,
    EVALUATION_INTERVAL,
    FINAL_STEP,
    IMPLEMENTATION_PATH,
    INFERENCE_SEED,
    MANIFEST_NAME,
    MODEL_PATH,
    SOURCE_STEP,
    TRAIN_SOURCE_MAX_EPOCHS,
    ArmSpec,
    BandExpectation,
    EvaluationSpec,
    materialize_fork,
    validate_materialized_fork,
)
from torch.distributed.checkpoint import FileSystemWriter, save

from prime_rl.orchestrator.types import Progress


def _write_toml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        tomli_w.dump(value, handle)


def _train_env(false_positive_rate: float, dataset_path: Path, *, explicit_defect_contract: bool = False) -> dict:
    args = {
        "dataset_path": str(dataset_path),
        "min_op": 10,
        "max_op": 40,
        "require_unique_prompts": True,
        "false_positive_rate": false_positive_rate,
        "defect_seed": 20260805,
    }
    if explicit_defect_contract:
        args.update(
            {
                "false_positive_rates_by_op": {},
                "false_positive_scope": "answer_correct_strict_wrong",
                "false_negative_rate": 0.0,
                "defect_draw_scope": "trajectory",
                "defect_assignment": "individual",
                "defect_gate_mode": "none",
                "defect_gate_probability": 1.0,
                "behavior_tax_c0": 0.0,
                "strict_reward_weight": 1.0,
            }
        )
    return {
        "id": "rsci-gsm-infinite",
        "name": "op10-40-strict",
        "group_size": 128,
        "args": args,
    }


def _eval_envs(interval: int, *, resolved: bool) -> list[dict]:
    envs = []
    for operation in range(11, 46):
        env = {
            "id": "rsci-gsm-infinite",
            "name": f"heldout-op{operation}-strict",
            "args": {"min_op": operation, "max_op": operation},
        }
        if resolved:
            env["interval"] = interval
        envs.append(env)
    return envs


def _write_source_configs(root: Path, false_positive_rate: float) -> None:
    _write_toml(
        root / "configs/trainer.toml",
        {
            "output_dir": str(root),
            "max_steps": 10000,
            "model": {"name": str(MODEL_PATH), "seq_len": 2048},
            "optim": {"type": "adamw", "lr": 1e-6},
            "scheduler": {"type": "constant"},
            "ckpt": {
                "interval": 25,
                "keep_last": 4,
                "keep_interval": 100,
                "weights_only": False,
                "skip_progress": False,
                "skip_scheduler": False,
                "skip_dataloader": False,
                "skip_optimizer": False,
            },
        },
    )
    _write_toml(
        root / "configs/orchestrator.toml",
        {
            "output_dir": str(root / "run_default"),
            "max_steps": 10000,
            "batch_size": 512,
            "group_size": 128,
            "seq_len": 2048,
            "student": {"model": {"name": str(MODEL_PATH)}},
            "train": {"env": [_train_env(false_positive_rate, root / "source-train.jsonl")]},
            "eval": {"interval": 25, "env": _eval_envs(25, resolved=True)},
            "ckpt": {"interval": CHECKPOINT_INTERVAL, "keep_last": 4, "keep_interval": 100},
        },
    )
    _write_toml(
        root / "configs/inference.toml",
        {"model": {"name": str(MODEL_PATH), "max_model_len": 2048}},
    )


def _write_config_inputs(repo: Path, spec: ArmSpec) -> None:
    _write_toml(
        repo / spec.base_config,
        {
            "output_dir": str(spec.source_root),
            "max_steps": 10000,
            "seq_len": 2048,
            "model": {"name": str(MODEL_PATH)},
            "ckpt": {"interval": CHECKPOINT_INTERVAL, "keep_last": 4, "keep_interval": 100},
            "trainer": {
                "optim": {"lr": 1e-6},
                "scheduler": {"type": "constant"},
            },
            "orchestrator": {
                "rollouts_per_example": 128,
                "train": {"env": [_train_env(spec.source_false_positive_rate, spec.source_training_dataset_path)]},
                "eval": {"interval": 25, "env": _eval_envs(25, resolved=False)},
            },
        },
    )
    _write_toml(
        repo / spec.common_config,
        {
            "max_steps": FINAL_STEP,
            "ckpt": {
                "resume_step": SOURCE_STEP,
                "interval": CHECKPOINT_INTERVAL,
                "keep_last": DESTINATION_KEEP_LAST,
                "keep_interval": DESTINATION_KEEP_INTERVAL,
            },
            "orchestrator": {
                "save_train_group_stats": True,
                "train_source_max_epochs": TRAIN_SOURCE_MAX_EPOCHS,
                "eval": {"interval": EVALUATION_INTERVAL},
            },
            "inference": {"seed": INFERENCE_SEED},
        },
    )
    _write_toml(
        repo / spec.arm_config,
        {
            "output_dir": str(spec.output_root),
            "slurm": {
                "job_name": spec.job_name,
                "project_dir": str(spec.output_root / "source_snapshot"),
            },
            "orchestrator": {
                "train": {
                    "env": [
                        _train_env(
                            spec.continuation_false_positive_rate,
                            spec.continuation_training_dataset_path,
                            explicit_defect_contract=True,
                        )
                    ]
                },
            },
        },
    )


def _write_resolved_configs(spec: ArmSpec) -> None:
    root = spec.output_root
    _write_toml(
        root / "configs/trainer.toml",
        {
            "output_dir": str(root),
            "max_steps": FINAL_STEP,
            "model": {"name": str(MODEL_PATH)},
            "optim": {"lr": 1e-6},
            "scheduler": {"type": "constant"},
            "ckpt": {
                "resume_step": SOURCE_STEP,
                "interval": CHECKPOINT_INTERVAL,
                "keep_last": DESTINATION_KEEP_LAST,
                "keep_interval": DESTINATION_KEEP_INTERVAL,
                "weights_only": False,
                "skip_progress": False,
                "skip_scheduler": False,
                "skip_dataloader": False,
                "skip_optimizer": False,
            },
        },
    )
    _write_toml(
        root / "configs/orchestrator.toml",
        {
            "output_dir": str(root / "run_default"),
            "max_steps": FINAL_STEP,
            "group_size": 128,
            "save_train_group_stats": True,
            "train_source_max_epochs": TRAIN_SOURCE_MAX_EPOCHS,
            "max_consecutive_zero_trainable_batches": 500,
            "train": {
                "env": [
                    _train_env(
                        spec.continuation_false_positive_rate,
                        spec.continuation_training_dataset_path,
                        explicit_defect_contract=True,
                    )
                ]
            },
            "eval": {
                "interval": EVALUATION_INTERVAL,
                "env": _eval_envs(EVALUATION_INTERVAL, resolved=True),
            },
            "ckpt": {
                "resume_step": SOURCE_STEP,
                "interval": CHECKPOINT_INTERVAL,
                "keep_last": DESTINATION_KEEP_LAST,
                "keep_interval": DESTINATION_KEEP_INTERVAL,
                "skip_progress": False,
            },
        },
    )
    _write_toml(
        root / "configs/inference.toml",
        {"seed": INFERENCE_SEED, "model": {"name": str(MODEL_PATH)}},
    )


def _write_evaluation(path: Path, categories: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, category in enumerate(categories):
        strict = float(category == "strict")
        answer = float(category in {"strict", "behavior_a"})
        rows.append(
            {
                "task": {"idx": index},
                "metrics": {
                    "strict_dependency_graph_reward": strict,
                    "answer_correct_metric": answer,
                },
                "rewards": {"reward": strict},
                "is_completed": True,
                "errors": [],
            }
        )
    path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))


def _make_spec(tmp_path: Path) -> tuple[ArmSpec, Path]:
    source = tmp_path / "source"
    output = tmp_path / "output"
    repo = tmp_path / "repo"
    source_dataset = source / "source-train.jsonl"
    continuation_dataset = tmp_path / "continuation/train.jsonl"
    evaluation = EvaluationSpec(
        operations=(11, 12),
        rows_per_operation=2,
        expected_bands=(
            BandExpectation(11, 11, strict=1, behavior_a=1, answer_wrong=0),
            BandExpectation(12, 12, strict=0, behavior_a=0, answer_wrong=2),
        ),
    )
    spec = ArmSpec(
        name="test_off",
        source_label="test_p05",
        source_root=source,
        output_root=output,
        base_config=Path("configs/base.toml"),
        common_config=Path("configs/common.toml"),
        arm_config=Path("configs/arm.toml"),
        source_false_positive_rate=0.05,
        continuation_false_positive_rate=0.0,
        job_name="test-withdrawal",
        source_training_dataset_path=source_dataset,
        continuation_training_dataset_path=continuation_dataset,
        evaluation=evaluation,
        trainer_shard_count=1,
    )
    source_dataset.parent.mkdir(parents=True, exist_ok=True)
    source_dataset.write_text('{"prompt":"source"}\n', encoding="utf-8")
    continuation_dataset.parent.mkdir(parents=True, exist_ok=True)
    continuation_dataset.write_text('{"prompt":"continuation"}\n', encoding="utf-8")
    continuation_sha256 = hashlib.sha256(continuation_dataset.read_bytes()).hexdigest()
    Path(f"{continuation_dataset}.manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": {
                    "path": str(continuation_dataset),
                    "sha256": continuation_sha256,
                    "rows": 1,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_source_configs(source, spec.source_false_positive_rate)
    (source / "rl.sbatch").write_text("#!/bin/bash\n", encoding="utf-8")
    dcp = source / f"checkpoints/step_{SOURCE_STEP}/trainer"
    save(
        {
            "app": {
                "model": {"weight": torch.ones(2)},
                "optimizers": {
                    "state": {
                        "weight": {
                            "step": torch.tensor(1),
                            "exp_avg": torch.zeros(2),
                        }
                    }
                },
                "scheduler": {"last_epoch": 3},
                "progress": {"step": SOURCE_STEP, "total_samples": 20, "total_tokens": 10},
            }
        },
        storage_writer=FileSystemWriter(dcp),
    )
    progress = source / f"run_default/checkpoints/step_{SOURCE_STEP}/orchestrator/progress.pt"
    progress.parent.mkdir(parents=True)
    torch.save(
        {"progress": Progress(step=SOURCE_STEP, total_tokens=10, total_samples=20, total_problems=30)},
        progress,
    )
    weights = source / f"weights/step_{SOURCE_STEP}"
    weights.mkdir(parents=True)
    (weights / "STABLE").touch()
    (weights / "config.json").write_text('{"model_type":"fake"}\n', encoding="utf-8")
    (weights / "model.safetensors").write_bytes(b"weights")
    rollout_root = source / f"run_default/rollouts/step_{SOURCE_STEP}"
    _write_evaluation(
        rollout_root / "eval_rollouts_heldout-op11-strict.jsonl",
        ("strict", "behavior_a"),
    )
    _write_evaluation(
        rollout_root / "eval_rollouts_heldout-op12-strict.jsonl",
        ("answer_wrong", "answer_wrong"),
    )
    _write_config_inputs(repo, spec)
    implementation = repo / IMPLEMENTATION_PATH
    implementation.parent.mkdir(parents=True, exist_ok=True)
    implementation.write_text("# test materializer\n", encoding="utf-8")
    return spec, repo


def test_materializer_copies_seed_independently_and_revalidates_hashes(tmp_path: Path) -> None:
    spec, repo = _make_spec(tmp_path)
    source_progress = spec.source_root / f"run_default/checkpoints/step_{SOURCE_STEP}/orchestrator/progress.pt"
    source_hash = hashlib.sha256(source_progress.read_bytes()).hexdigest()

    materialize_fork(spec, repo_root=repo)
    destination_progress = spec.output_root / f"run_default/checkpoints/step_{SOURCE_STEP}/orchestrator/progress.pt"
    assert not destination_progress.samefile(source_progress)
    assert destination_progress.stat().st_ino != source_progress.stat().st_ino
    assert hashlib.sha256(source_progress.read_bytes()).hexdigest() == source_hash

    _write_resolved_configs(spec)
    result = validate_materialized_fork(
        spec.output_root / MANIFEST_NAME,
        spec=spec,
        repo_root=repo,
    )
    assert result["arm"] == spec.name
    assert result["source_step"] == SOURCE_STEP

    implementation = repo / IMPLEMENTATION_PATH
    original_implementation = implementation.read_bytes()
    implementation.write_bytes(b"# changed materializer\n")
    with pytest.raises(ValueError, match="implementation identity changed"):
        validate_materialized_fork(
            spec.output_root / MANIFEST_NAME,
            spec=spec,
            repo_root=repo,
        )
    implementation.write_bytes(original_implementation)

    source_sbatch = spec.source_root / "rl.sbatch"
    original_sbatch = source_sbatch.read_bytes()
    source_sbatch.write_bytes(b"#!/bin/bash\n# changed\n")
    with pytest.raises(ValueError, match="source rl.sbatch identity changed"):
        validate_materialized_fork(
            spec.output_root / MANIFEST_NAME,
            spec=spec,
            repo_root=repo,
        )
    source_sbatch.write_bytes(original_sbatch)

    original_dataset = spec.continuation_training_dataset_path.read_bytes()
    spec.continuation_training_dataset_path.write_bytes(b'{"prompt":"changed"}\n')
    with pytest.raises(ValueError, match="Adjacent dataset manifest does not bind"):
        validate_materialized_fork(
            spec.output_root / MANIFEST_NAME,
            spec=spec,
            repo_root=repo,
        )
    spec.continuation_training_dataset_path.write_bytes(original_dataset)

    destination_weights = spec.output_root / f"weights/step_{SOURCE_STEP}/model.safetensors"
    destination_weights.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="hashes changed"):
        validate_materialized_fork(
            spec.output_root / MANIFEST_NAME,
            spec=spec,
            repo_root=repo,
        )
    assert hashlib.sha256(source_progress.read_bytes()).hexdigest() == source_hash


def test_pristine_guard_allows_seal_artifacts_and_rejects_runtime_output(tmp_path: Path) -> None:
    spec, repo = _make_spec(tmp_path)
    materialize_fork(spec, repo_root=repo)
    _write_resolved_configs(spec)
    (spec.output_root / "source_snapshot/user/runtime").mkdir(parents=True)
    (spec.output_root / "source_snapshot/user/runtime/module.py").write_text("value = 1\n", encoding="utf-8")
    for name in (
        "source_provenance.json",
        "source_provenance.lock",
        "source_environment.freeze.txt",
        "rl.sbatch",
        "STATUS.md",
    ):
        (spec.output_root / name).write_text("sealed\n", encoding="utf-8")

    validate_materialized_fork(
        spec.output_root / MANIFEST_NAME,
        spec=spec,
        repo_root=repo,
        require_pristine=True,
    )

    runtime_log = spec.output_root / "logs/orchestrator.log"
    runtime_log.parent.mkdir()
    runtime_log.write_text("started\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected pre-submission"):
        validate_materialized_fork(
            spec.output_root / MANIFEST_NAME,
            spec=spec,
            repo_root=repo,
            require_pristine=True,
        )
