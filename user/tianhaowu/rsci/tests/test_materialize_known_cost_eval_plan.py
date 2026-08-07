from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import materialize_known_cost_eval_plan as eval_plan
import pytest
from materialize_known_cost_eval_plan import (
    RECEIPT_ARTIFACT_TYPE,
    SCHEMA_VERSION,
    SUCCESS_ARTIFACT_NAMES,
    build_task_bundle,
    bytes_sha256,
    canonical_json_bytes,
    deduplicate_model_records,
    eligible_runs_from_launch_intent,
    file_identity,
    raw_groups_before_step,
    resolve_raw_clock_bracket,
    validate_receipt_chain,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _checkpoint(path: Path, content: bytes, *, stable: bool = True) -> Path:
    path.mkdir(parents=True)
    if stable:
        (path / "STABLE").touch()
    (path / "config.json").write_text("{}\n", encoding="utf-8")
    (path / "model.safetensors").write_bytes(content)
    return path


def test_eval_run_inventory_is_derived_exactly_from_launch_intent(tmp_path: Path) -> None:
    filenames = ["b20260808_g_p0125.toml", "b20260808_t_p0125.toml"]
    eligible_runs = []
    for filename in filenames:
        run_dir = tmp_path / Path(filename).stem
        run_dir.mkdir()
        eligible_runs.append(
            {
                "arm_filename": filename,
                "output_dir": str(run_dir),
                "resolved_configs": {
                    "trainer": {"path": "/trainer", "sha256": "a" * 64},
                    "orchestrator": {"path": "/orchestrator", "sha256": "b" * 64},
                    "inference": {"path": "/inference", "sha256": "c" * 64},
                },
                "source_provenance": {"manifest": {"path": "/source", "sha256": "d" * 64}},
                "sbatch": {"path": "/sbatch", "sha256": "e" * 64},
            }
        )
    intent = {
        "schema_version": 1,
        "artifact_type": "rsci_known_cost_boundary_submission_intent",
        "study_id": "verifier-defect-known-cost-boundary-v1",
        "preregistered_decision": {
            "eligible_arm_count": len(filenames),
            "eligible_arm_filenames": filenames,
        },
        "eligible_runs": eligible_runs,
    }

    runs = eligible_runs_from_launch_intent(intent)

    assert [run["run_id"] for run in runs] == ["b20260808-g-p0125", "b20260808-t-p0125"]
    assert {run["arm_filename"] for run in runs} == set(filenames)

    incomplete = copy.deepcopy(intent)
    incomplete["eligible_runs"].pop()
    with pytest.raises(ValueError, match="invalid eligible-run inventory"):
        eligible_runs_from_launch_intent(incomplete)


def test_raw_clock_targets_are_exact_or_two_endpoint_brackets() -> None:
    points = [
        {"step": 0, "raw_groups": 0},
        {"step": 325, "raw_groups": 2_800},
        {"step": 375, "raw_groups": 3_000},
        {"step": 725, "raw_groups": 5_800},
        {"step": 775, "raw_groups": 6_200},
        {"step": 1_500, "raw_groups": 12_100},
    ]

    exact = resolve_raw_clock_bracket(points, 3_000)
    bracketed = resolve_raw_clock_bracket(points, 6_000)

    assert exact["mode"] == "exact"
    assert exact["lower"] == exact["upper"] == {"step": 375, "raw_groups": 3_000}
    assert bracketed["mode"] == "bracketed"
    assert bracketed["lower"] == {"step": 725, "raw_groups": 5_800}
    assert bracketed["upper"] == {"step": 775, "raw_groups": 6_200}
    assert bracketed["interpolation_weight_upper"] == 0.5
    assert "neither endpoint" in bracketed["analysis_rule"]
    assert raw_groups_before_step((0, 24, 24, 25, 100), 25) == 3

    with pytest.raises(ValueError, match="not bracketed"):
        resolve_raw_clock_bracket(points, 13_000)
    with pytest.raises(ValueError, match="multiple retained checkpoints"):
        resolve_raw_clock_bracket(
            [
                {"step": 0, "raw_groups": 0},
                {"step": 25, "raw_groups": 200},
                {"step": 50, "raw_groups": 200},
                {"step": 75, "raw_groups": 400},
            ],
            200,
        )


def test_step_zero_is_deduplicated_but_retained_steps_are_run_specific(tmp_path: Path) -> None:
    base = _checkpoint(tmp_path / "base", b"base", stable=False)
    arm_a = _checkpoint(tmp_path / "arm-a-step-375", b"a")
    arm_b = _checkpoint(tmp_path / "arm-b-step-375", b"b")
    run_records = [
        {
            "run_id": run_id,
            "selected_checkpoints": [
                {"step": 0, "raw_groups": 0, "roles": [{"clock": "initialization"}]},
                {"step": 375, "raw_groups": 3_000, "roles": [{"clock": "optimizer_step"}]},
            ],
        }
        for run_id in ("arm-a", "arm-b")
    ]
    selected_paths = {
        "arm-a": {0: base, 375: arm_a},
        "arm-b": {0: base, 375: arm_b},
    }

    models = deduplicate_model_records(run_records, selected_paths)

    assert len(models) == 3
    assert models[0]["step_zero_deduplicated"] is True
    assert [item["run_id"] for item in models[0]["occurrences"]] == ["arm-a", "arm-b"]
    assert {model["occurrences"][0]["run_id"] for model in models[1:]} == {"arm-a", "arm-b"}


def test_task_bundle_seals_untagged_and_six_paired_tagged_shards(tmp_path: Path) -> None:
    model = {
        "model_key": "arm-a__step_1375__0123456789abcdef",
        "checkpoint": {
            "resolved_path": str((tmp_path / "model").resolve()),
            "inventory_sha256": "a" * 64,
        },
    }
    task, artifacts = build_task_bundle(
        model=model,
        task_index=7,
        plan_root=(tmp_path / "plan").resolve(),
        evaluator_path=REPO_ROOT / "user/tianhaowu/rsci/figure3_eval.py",
        tagged_data_dir=(tmp_path / "tagged").resolve(),
        tokenizer_path=(tmp_path / "tokenizer").resolve(),
        request_seed=20_260_807,
    )

    assert len(task["shards"]) == 7
    assert len(artifacts) == 8
    assert task["shards"][0]["shard_id"] == "untagged"
    assert [shard["neutral_tag_index"] for shard in task["shards"][1:]] == list(range(6))
    assert len({shard["output_dir"] for shard in task["shards"]}) == 7
    inference = tomllib.loads(artifacts[0].content.decode("utf-8"))
    assert inference["vllm_extra"]["tokenizer"] == str((tmp_path / "tokenizer").resolve())
    for tag_index, artifact in enumerate(artifacts[2:]):
        config = tomllib.loads(artifact.content.decode("utf-8"))
        assert config["eval"]["neutral_tag_filter"] == tag_index
        assert config["eval"]["request_seed_mode"] == "paired_source_v1"
        assert Path(config["eval"]["output_dir"]).parts[-2:] == ("tagged", f"tag_{tag_index}")

    materialized = artifacts[0]
    eval_plan._write_bytes_once(materialized.path, materialized.content)
    assert materialized.path.stat().st_mode & 0o222 == 0
    build = eval_plan.PlanBuild(
        manifest={"tasks": []},
        manifest_bytes=b"",
        plan_path=tmp_path / "plan" / "plan.json",
        config_artifacts=(materialized,),
    )
    eval_plan._validate_materialized_configs(build)
    materialized.path.chmod(0o644)
    with pytest.raises(ValueError, match="Materialized evaluation config must be read-only"):
        eval_plan._validate_materialized_configs(build)
    with pytest.raises(ValueError, match="Immutable evaluation artifact must be read-only"):
        eval_plan._write_bytes_once(materialized.path, materialized.content)


def test_receipt_chain_requires_exact_predecessor_and_stops_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_plan, "_validate_completed_shard", lambda shard: None)
    output_dir = tmp_path / "results" / "untagged"
    output_dir.mkdir(parents=True)
    for name in SUCCESS_ARTIFACT_NAMES:
        (output_dir / name).write_text(f"{name}\n", encoding="utf-8")
    task = {
        "task_id": "task-a",
        "config_bundle_sha256": "b" * 64,
        "checkpoint_inventory_sha256": "c" * 64,
        "result_root": str((tmp_path / "results").resolve()),
        "shards": [{"shard_id": "untagged", "output_dir": str(output_dir.resolve())}],
    }
    plan = {
        "plan_id": "d" * 64,
        "plan_root": str(tmp_path.resolve()),
        "tasks": [task],
    }
    receipt_dir = tmp_path / "receipts" / "task-a"
    receipt_dir.mkdir(parents=True)
    first = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "plan_id": plan["plan_id"],
        "plan_sha256": "e" * 64,
        "task_id": "task-a",
        "attempt": 1,
        "predecessor_receipt_sha256": None,
        "config_bundle_sha256": task["config_bundle_sha256"],
        "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
        "result_root": task["result_root"],
        "status": "failed",
        "started_at": "2026-08-08T00:00:00Z",
        "finished_at": "2026-08-08T00:01:00Z",
        "scheduler": {"job_id": "123", "array_task_id": 0},
        "exit_code": 1,
        "failure": "node failure",
    }
    first_bytes = canonical_json_bytes(first)
    first_path = receipt_dir / "attempt_0001.json"
    first_path.write_bytes(first_bytes)
    first_path.chmod(0o444)
    assert first_path.stat().st_mode & 0o222 == 0
    second = {
        **first,
        "attempt": 2,
        "predecessor_receipt_sha256": bytes_sha256(first_bytes),
        "status": "succeeded",
        "started_at": "2026-08-08T00:02:00Z",
        "finished_at": "2026-08-08T00:03:00Z",
        "scheduler": {"job_id": "124", "array_task_id": 0},
        "exit_code": 0,
        "shards": [
            {
                "shard_id": "untagged",
                "output_dir": str(output_dir.resolve()),
                "artifacts": {name: file_identity(output_dir / name) for name in SUCCESS_ARTIFACT_NAMES},
            }
        ],
    }
    second.pop("failure")
    second_bytes = canonical_json_bytes(second)
    second_path = receipt_dir / "attempt_0002.json"
    second_path.write_bytes(second_bytes)
    second_path.chmod(0o444)
    assert second_path.stat().st_mode & 0o222 == 0

    summary = validate_receipt_chain(plan=plan, plan_sha256="e" * 64)
    assert summary == {"receipt_count": 2, "task_statuses": {"task-a": "succeeded"}}

    second_path.chmod(0o644)
    with pytest.raises(ValueError, match="Evaluation attempt receipt must be read-only"):
        validate_receipt_chain(plan=plan, plan_sha256="e" * 64)
    second_path.chmod(0o444)

    third = copy.deepcopy(first)
    third.update(
        {
            "attempt": 3,
            "predecessor_receipt_sha256": bytes_sha256(second_bytes),
            "started_at": "2026-08-08T00:04:00Z",
            "finished_at": "2026-08-08T00:05:00Z",
            "scheduler": {"job_id": "125", "array_task_id": 0},
        }
    )
    third_path = receipt_dir / "attempt_0003.json"
    third_path.write_bytes(canonical_json_bytes(third))
    third_path.chmod(0o444)
    with pytest.raises(ValueError, match="follows a succeeded attempt"):
        validate_receipt_chain(plan=plan, plan_sha256="e" * 64)
