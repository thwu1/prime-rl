import hashlib
import json
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import analyze_verifier_exposure as exposure_analysis
import figure3_eval
import pytest
import solution_graph
import tomli_w
from analyze_verifier_exposure import (
    CONFIRMATORY_ARM_SPECS,
    CONFIRMATORY_TIER,
    LEGACY_TIER,
    EvalPoint,
    PromptExposureAudit,
    RunSeries,
    SourceProvenanceIdentity,
    _normalized_frozen_config_hashes,
    exposure_by_eval_step,
    interpolate,
    load_audit_exposure_index,
    load_confirmatory_run,
    normalized_auc,
    parse_args,
    parse_eval_log,
    summarize,
    sustained_discovery,
)
from figure3_eval import (
    GENERATION_COMPLETION_NAME,
    GENERATION_MANIFEST_NAME,
    build_generation_manifest,
    canonical_generation_content,
    deterministic_strict_results,
    file_sha256,
    generation_completion_payload,
    implementation_identity,
    load_rows,
)

OPS = tuple(range(11, 46))


@pytest.fixture(autouse=True)
def _stub_source_provenance(monkeypatch):
    def load_identity(run_dir: Path) -> SourceProvenanceIdentity:
        return SourceProvenanceIdentity(
            manifest_path=(run_dir / "source_provenance.json").resolve(),
            parent_commit_sha="a" * 40,
            submodules=(("deps/verifiers", "b" * 40),),
            source_tree_sha256="c" * 64,
            uv_lock_sha256="d" * 64,
            pip_freeze_sha256="e" * 64,
            launch_inputs_sha256="4" * 64,
            launch_artifacts_sha256={
                "configs/inference.toml": "f" * 64,
                "configs/orchestrator.toml": "1" * 64,
                "configs/trainer.toml": "2" * 64,
                "rl.sbatch": "3" * 64,
            },
        )

    monkeypatch.setattr(exposure_analysis, "load_source_provenance_identity", load_identity)


def _point(step: int, exposure: int, score: float) -> EvalPoint:
    return EvalPoint(
        step=step,
        finalized_groups=exposure,
        exposure=exposure,
        scores={15: score},
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _group(
    group_id: str,
    group_index: int,
    label: int,
    *,
    errored: list[bool] | None = None,
    appended: list[bool] | None = None,
    size: int = 4,
    optimized_proxy_metric: str | None = None,
    false_positive_rate: float = 0.0,
    defect_seed: int = 20260805,
    candidate_slots: tuple[int, ...] = (),
    strict_slots: tuple[int, ...] = (),
) -> dict[str, object]:
    errored = errored or [False] * size
    appended = appended or [True] * size
    in_advantage = [not value for value in errored]
    row: dict[str, object] = {
        "group_id": group_id,
        "group_index": group_index,
        "finalized_before_optimizer_step": label,
        "target_size": size,
        "received_size": size,
        "sample_ids": [f"sample-{group_id}"] * size,
        "operations": [10] * size,
        "trace_ids": [f"trace-{group_id}-{slot}" for slot in range(size)],
        "rollout_slots": list(range(size)),
        "expected_rollout_slots": list(range(size)),
        "advantage_population_size": sum(in_advantage),
        "errored": errored,
        "in_advantage_population": in_advantage,
        "appended_to_batch": appended,
    }
    if optimized_proxy_metric is not None:
        if set(candidate_slots) & set(strict_slots):
            raise ValueError("Fixture candidate and strict slots must be disjoint")
        sample_id = f"sample-{group_id}"

        def draw(slot: int, *, shuffled: bool) -> float:
            draw_key = json.dumps([sample_id, slot], separators=(",", ":"))
            prefix = f"{defect_seed}:group-shuffle:" if shuffled else f"{defect_seed}:"
            digest = hashlib.sha256(f"{prefix}{draw_key}".encode()).digest()
            return int.from_bytes(digest[:8], "big") / 2**64

        valid = [not value for value in errored]
        strict = [float(is_valid and slot in strict_slots) for slot, is_valid in enumerate(valid)]
        answer_correct = [
            float(is_valid and (slot in candidate_slots or slot in strict_slots)) for slot, is_valid in enumerate(valid)
        ]
        candidates = [
            float(strict_value == 0.0 and answer == 1.0) for strict_value, answer in zip(strict, answer_correct)
        ]
        defect_draws = [draw(slot, shuffled=False) for slot in range(size)]
        shuffle_draws = [draw(slot, shuffled=True) for slot in range(size)]
        behavior_triggers = [
            float(is_valid and candidate == 1.0 and defect_draw < false_positive_rate)
            for is_valid, candidate, defect_draw in zip(valid, candidates, defect_draws, strict=True)
        ]
        realized_k = int(sum(behavior_triggers))
        strict_negative_indices = [
            slot
            for slot, (is_valid, strict_value) in enumerate(zip(valid, strict, strict=True))
            if is_valid and not strict_value
        ]
        shuffled_indices = set(
            sorted(strict_negative_indices, key=lambda slot: (shuffle_draws[slot], slot))[:realized_k]
        )
        shuffled_triggers = [float(slot in shuffled_indices) for slot in range(size)]
        behavior_proxy = [
            strict_value + trigger for strict_value, trigger in zip(strict, behavior_triggers, strict=True)
        ]
        shuffled_proxy = [
            strict_value + trigger for strict_value, trigger in zip(strict, shuffled_triggers, strict=True)
        ]
        optimized = behavior_proxy if optimized_proxy_metric == "behavior_proxy_reward" else shuffled_proxy
        selected_triggers = (
            behavior_triggers if optimized_proxy_metric == "behavior_proxy_reward" else shuffled_triggers
        )
        row["rewards"] = list(optimized)
        row["metrics"] = {
            "proxy_reward": list(optimized),
            "behavior_proxy_reward": list(behavior_proxy),
            "shuffled_proxy_reward": list(shuffled_proxy),
            "strict_dependency_graph_reward": strict,
            "answer_correct_metric": answer_correct,
            "defect_triggered_metric": list(selected_triggers),
            "behavior_triggered_metric": behavior_triggers,
            "shuffled_triggered_metric": shuffled_triggers,
            "false_negative_triggered_metric": [0.0] * size,
            "defect_draw_metric": defect_draws,
            "shuffle_draw_metric": shuffle_draws,
            "defect_rate_metric": [false_positive_rate] * size,
            "defect_rollout_slot_metric": [float(slot) for slot in range(size)],
            "matched_extra_positive_count_metric": [float(realized_k)] * size,
            "defect_candidate_metric": candidates,
            "defect_eligible_metric": list(candidates),
            "valid_rollout_metric": [float(not value) for value in errored],
        }
    return row


def _attempt(
    number: int,
    step: int,
    group_id: str,
    count: int,
    *,
    trainable: int | None = None,
) -> dict[str, object]:
    trainable = count if trainable is None else trainable
    return {
        "batch_attempt": number,
        "optimizer_step": step,
        "eligible_to_ship": trainable > 0,
        "n_rollouts": count,
        "n_trainable": trainable,
        "group_slices": [{"group_id": group_id, "count": count, "trainable_count": trainable}],
    }


def _write_toml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        tomli_w.dump(payload, handle)


def _write_frozen_eval(
    root: Path,
    step: int,
    model_path: Path,
    dataset_dir: Path,
    *,
    expected_rows: int = 1,
) -> None:
    output_dir = root / "evals" / "op11-45" / f"step_{step}"
    inference_path = output_dir / "configs" / "inference.toml"
    eval_path = output_dir / "configs" / "eval.toml"
    data_sources = [{"min_op": 11, "max_op": 45, "data_dir": str(dataset_dir)}]
    eval_config = {
        "infer_config": str(inference_path),
        "evaluator": str(root / "source_snapshot" / "user" / "tianhaowu" / "rsci" / "figure3_eval.py"),
        "eval": {
            "data_sources": data_sources,
            "operations": list(OPS),
            "examples_per_operation": expected_rows,
            "output_dir": str(output_dir),
            "model": str(model_path),
            "samples_per_prompt": 1,
            "pass_at": [1],
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "max_tokens": 2048,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_seed": 20260807,
        },
    }
    _write_toml(eval_path, eval_config)
    _write_toml(
        inference_path,
        {
            "output_dir": str(output_dir / "deployment"),
            "server": {"host": "0.0.0.0", "port": 20000 + step, "liveness_timeout_seconds": 30.0},
            "model": {"name": str(model_path), "dtype": "auto", "max_model_len": 2048},
        },
    )

    generation_rows = [
        {
            "op": operation,
            "id": f"op{operation}-row{row}",
            "__idx": row,
            "template": "fixture",
            "mode": None,
            "sample_rank": 0,
            "finish_reason": "stop",
            "gen_solution_answer": "<answer>0</answer>",
        }
        for operation in OPS
        for row in range(expected_rows)
    ]
    generations_path = output_dir / "generations.jsonl"
    _write_jsonl(generations_path, generation_rows)
    dataset_rows, hashes = load_rows(eval_config["eval"])
    manifest = build_generation_manifest(eval_config, dataset_rows, hashes)
    manifest_path = output_dir / GENERATION_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    canonical, canonical_records = canonical_generation_content(generations_path, dataset_rows, 1)
    completion = generation_completion_payload(output_dir, manifest, canonical, len(canonical_records))
    (output_dir / GENERATION_COMPLETION_NAME).write_text(json.dumps(completion) + "\n", encoding="utf-8")
    strict_rows = deterministic_strict_results(dataset_rows, canonical_records)
    strict_path = output_dir / "strict_results.jsonl"
    _write_jsonl(strict_path, strict_rows)
    scorer_identity = implementation_identity()
    per_op = {str(operation): {"empirical": {"pass@1": 0.0}, "unbiased": {"pass@1": 0.0}} for operation in OPS}
    metrics = {
        "model": str(model_path),
        "data_sources": data_sources,
        "dataset_sha256_by_op": hashes,
        "operations": list(OPS),
        "num_prompts": len(strict_rows),
        "samples_per_prompt": 1,
        "num_generations": len(strict_rows),
        "strict_graph": {
            "total": {"empirical": {"pass@1": 0.0}, "unbiased": {"pass@1": 0.0}},
            "per_op": per_op,
        },
        "sampling": {
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "max_tokens": 2048,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_seed": 20260807,
        },
        "generation_provenance": {
            **completion,
            "generation_manifest": GENERATION_MANIFEST_NAME,
            "generation_completion": GENERATION_COMPLETION_NAME,
        },
        "strict_scoring_provenance": {
            "implementation_sha256": scorer_identity,
            "strict_results_sha256": file_sha256(strict_path),
            "num_results": len(strict_rows),
        },
        "implementation_sha256": scorer_identity,
    }
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics) + "\n", encoding="utf-8")


def _confirmatory_run(tmp_path: Path, label: str = "B1") -> Path:
    root = tmp_path / f"experiment-{label}"
    rollouts = root / "rollouts"
    snapshot_source = root / "source_snapshot" / "user" / "tianhaowu" / "rsci"
    snapshot_source.mkdir(parents=True)
    (snapshot_source / "figure3_eval.py").write_bytes(Path(figure3_eval.__file__).read_bytes())
    (snapshot_source / "solution_graph.py").write_bytes(Path(solution_graph.__file__).read_bytes())
    base_model = tmp_path / "base-model"
    base_model.mkdir(exist_ok=True)
    checkpoint = root / "weights" / "step_1"
    checkpoint.mkdir(parents=True)
    (checkpoint / "STABLE").touch()
    dataset_path = tmp_path / "train.jsonl"
    dataset_path.write_text('{"fixture": true}\n', encoding="utf-8")
    assignment, rate = CONFIRMATORY_ARM_SPECS[label]
    orchestrator_config = {
        "save_train_group_stats": True,
        "batch_size": 512,
        "group_size": 128,
        "max_steps": 500,
        "student": {"model": {"name": str(base_model)}},
        "train": {
            "env": [
                {
                    "id": "rsci-gsm-infinite",
                    "name": "op10-40-strict",
                    "group_size": 128,
                    "args": {
                        "dataset_path": str(dataset_path),
                        "min_op": 10,
                        "max_op": 40,
                        "require_unique_prompts": True,
                        "false_positive_rate": rate,
                        "false_positive_scope": "answer_correct_strict_wrong",
                        "false_negative_rate": 0.0,
                        "defect_assignment": assignment,
                        "defect_draw_scope": "sample_slot",
                        "defect_seed": 20260805,
                    },
                }
            ]
        },
    }
    _write_toml(root / "configs" / "orchestrator.toml", orchestrator_config)
    _write_toml(root / "configs" / "trainer.toml", {"max_steps": 500, "model": {"name": str(base_model)}})
    _write_toml(
        root / "configs" / "inference.toml",
        {"seed": 0, "model": {"name": str(base_model), "max_model_len": 2048}},
    )

    dataset_dir = tmp_path / "datasets"
    for operation in OPS:
        _write_jsonl(
            dataset_dir / f"op{operation}-1.jsonl",
            [
                {
                    "op": operation,
                    "id": f"op{operation}-row0",
                    "problem": "fixture problem",
                    "question": "fixture question",
                    "solution": "Answer: 1",
                    "template": "fixture",
                }
            ],
        )
    proxy_metric = f"{assignment.removesuffix('_group')}_proxy_reward"
    _write_jsonl(
        rollouts / "train_group_stats.jsonl",
        [
            _group(
                "g0",
                1,
                0,
                size=128,
                optimized_proxy_metric=proxy_metric,
                false_positive_rate=rate,
            )
        ],
    )
    _write_jsonl(rollouts / "train_batch_attempts.jsonl", [_attempt(1, 0, "g0", 128)])
    _write_frozen_eval(root, 0, base_model.resolve(), dataset_dir.resolve())
    _write_frozen_eval(root, 1, checkpoint.resolve(), dataset_dir.resolve())

    # Frozen analysis must not consult mixed-policy live-eval diagnostics.
    log_path = root / "logs" / "orchestrator.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "Eval heldout-op15-strict step 1 had mixed policy versions: [0, 1]\n",
        encoding="utf-8",
    )
    return root


def _five_arm_clones(run: RunSeries) -> tuple[RunSeries, ...]:
    assert run.training_identity is not None
    assert run.reward_audit is not None
    clones = []
    for label, (assignment, rate) in CONFIRMATORY_ARM_SPECS.items():
        identity = replace(
            run.training_identity,
            label=label,
            defect_assignment=assignment,
            false_positive_rate=rate,
        )
        reward_audit = replace(
            run.reward_audit,
            optimized_proxy_metric=f"{assignment.removesuffix('_group')}_proxy_reward",
        )
        clones.append(replace(run, label=label, training_identity=identity, reward_audit=reward_audit))
    return tuple(clones)


def test_frozen_config_normalization_excludes_only_per_task_logistics(tmp_path: Path) -> None:
    first_eval = {
        "infer_config": str(tmp_path / "arm-a" / "inference.toml"),
        "evaluator": str(tmp_path / "arm-a" / "source_snapshot" / "figure3_eval.py"),
        "eval": {
            "output_dir": str(tmp_path / "arm-a" / "step_0"),
            "model": str(tmp_path / "base-model"),
            "api_base_url": "http://127.0.0.1:21001/v1",
            "operations": [11],
            "temperature": 0.7,
        },
    }
    first_inference = {
        "output_dir": str(tmp_path / "arm-a" / "deployment"),
        "server": {"host": "0.0.0.0", "port": 21001, "liveness_timeout_seconds": 30.0},
        "model": {"name": str(tmp_path / "base-model"), "dtype": "auto", "max_model_len": 2048},
    }
    second_eval = {
        **first_eval,
        "infer_config": str(tmp_path / "arm-b" / "inference.toml"),
        "evaluator": str(tmp_path / "arm-b" / "source_snapshot" / "figure3_eval.py"),
        "eval": {
            **first_eval["eval"],
            "output_dir": str(tmp_path / "arm-b" / "step_25"),
            "model": str(tmp_path / "step_25"),
            "api_base_url": "http://127.0.0.1:32767/v1",
        },
    }
    second_inference = {
        **first_inference,
        "output_dir": str(tmp_path / "arm-b" / "deployment"),
        "server": {**first_inference["server"], "port": 32767},
        "model": {**first_inference["model"], "name": str(tmp_path / "step_25")},
    }

    assert _normalized_frozen_config_hashes(first_eval, first_inference) == _normalized_frozen_config_hashes(
        second_eval,
        second_inference,
    )

    second_inference["model"]["max_model_len"] = 4096
    assert _normalized_frozen_config_hashes(first_eval, first_inference) != _normalized_frozen_config_hashes(
        second_eval,
        second_inference,
    )


def test_exposure_parser_uses_latest_finalized_group_count(tmp_path):
    log_path = tmp_path / "orchestrator.log"
    log_path.write_text(
        "\n".join(
            [
                "eval was triggered at step 0",
                "pipeline | groups fin=4 drop(all_failed=0)",
                "eval was triggered at step 25",
                "pipeline | groups fin=9 drop(all_failed=0)",
                "eval was triggered at step 50",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert exposure_by_eval_step(log_path) == {0: 0, 25: 4, 50: 9}


def test_audit_exposure_uses_strict_cutoff_and_reports_sensitivities(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    _write_jsonl(
        groups_path,
        [
            _group(
                "g0",
                1,
                0,
                errored=[False, False, True, False],
                appended=[True, True, False, True],
            ),
            _group("g1", 2, 1),
        ],
    )
    _write_jsonl(
        attempts_path,
        [
            _attempt(1, 0, "g0", 3),
            _attempt(2, 1, "g1", 4),
        ],
    )

    audit = load_audit_exposure_index(groups_path, attempts_path)

    assert audit.counts_before(0).attempted_slots == 0
    cutoff_one = audit.counts_before(1)
    assert cutoff_one.attempted_slots == 4
    assert cutoff_one.received_slots == 4
    assert cutoff_one.valid_slots == 3
    assert cutoff_one.buffer_appended_slots == 3
    assert cutoff_one.shipped_slots == 3
    assert audit.counts_before(2).attempted_slots == 8
    assert cutoff_one.as_dict()["valid_over_attempted"] == 0.75


def test_audit_distinguishes_assembled_from_shipped_and_requires_contiguous_steps(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    _write_jsonl(groups_path, [_group("g0", 1, 0), _group("g1", 2, 0), _group("g2", 3, 2)])
    _write_jsonl(
        attempts_path,
        [
            _attempt(1, 0, "g0", 4, trainable=0),
            _attempt(2, 0, "g1", 4),
            _attempt(3, 2, "g2", 4),
        ],
    )

    audit = load_audit_exposure_index(groups_path, attempts_path)
    counts = audit.counts_before(1).as_dict()
    assert counts["attempted_slots"] == 8
    assert counts["assembled_slots"] == 8
    assert counts["shipped_slots"] == 4
    assert counts["trainable_shipped_slots"] == 4
    with pytest.raises(ValueError, match=r"not contiguous.*missing=\[1\]"):
        audit.require_contiguous_shipped_steps(3)


def test_group_reward_audit_rejects_proxy_or_counterfactual_mismatch(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    group = _group(
        "g0",
        1,
        0,
        optimized_proxy_metric="behavior_proxy_reward",
        false_positive_rate=1.0,
        candidate_slots=(0,),
    )
    group["rewards"][0] = 0.0
    _write_jsonl(groups_path, [group])
    _write_jsonl(attempts_path, [_attempt(1, 0, "g0", 4)])

    with pytest.raises(ValueError, match="optimized rewards"):
        load_audit_exposure_index(
            groups_path,
            attempts_path,
            "behavior_proxy_reward",
            false_positive_rate=1.0,
            defect_seed=20260805,
        )


def test_group_reward_audit_reconstructs_exact_treatment_and_shuffle(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    group = _group(
        "g0",
        1,
        0,
        optimized_proxy_metric="shuffled_proxy_reward",
        false_positive_rate=1.0,
        candidate_slots=(0,),
        strict_slots=(1,),
    )
    _write_jsonl(groups_path, [group])
    _write_jsonl(attempts_path, [_attempt(1, 0, "g0", 4)])

    audit = load_audit_exposure_index(
        groups_path,
        attempts_path,
        "shuffled_proxy_reward",
        false_positive_rate=1.0,
        defect_seed=20260805,
    )

    summary = audit.reward_audit.as_dict()
    assert summary["realized_k_total"] == 1
    assert summary["candidate_opportunities"] == 1
    assert summary["eligible_opportunities"] == 1


@pytest.mark.parametrize(
    ("metric_name", "index", "replacement", "match"),
    [
        ("answer_correct_metric", 0, 0.0, "candidate_metric does not match strict/answer"),
        ("defect_candidate_metric", 0, 0.0, "candidate_metric does not match strict/answer"),
        ("defect_eligible_metric", 0, 0.0, "eligible_metric does not match candidate"),
        ("defect_draw_metric", 0, 0.0, "defect_draw_metric does not match deterministic"),
        ("shuffle_draw_metric", 0, 0.0, "shuffle_draw_metric does not match deterministic"),
        ("defect_rate_metric", 0, 0.5, "defect_rate_metric does not match configured"),
        ("defect_rollout_slot_metric", 0, 1.0, "does not match verifier-reported rollout_slots"),
        ("behavior_triggered_metric", 0, 0.0, "behavior_triggered_metric does not match reconstructed"),
        ("behavior_proxy_reward", 0, 0.0, "behavior_proxy_reward does not match strict plus valid trigger"),
        ("false_negative_triggered_metric", 0, 1.0, "false_negative_triggered_metric must be zero"),
        ("defect_triggered_metric", 0, 0.0, "defect_triggered_metric does not match selected assignment"),
        ("valid_rollout_metric", 0, 0.0, "valid_rollout_metric disagrees"),
        ("matched_extra_positive_count_metric", 0, 0.0, "does not equal reconstructed K=1"),
    ],
)
def test_group_reward_audit_rejects_impossible_treatment_evidence(
    tmp_path,
    metric_name,
    index,
    replacement,
    match,
):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    group = _group(
        "g0",
        1,
        0,
        optimized_proxy_metric="behavior_proxy_reward",
        false_positive_rate=1.0,
        candidate_slots=(0,),
        strict_slots=(1,),
    )
    group["metrics"][metric_name][index] = replacement
    _write_jsonl(groups_path, [group])
    _write_jsonl(attempts_path, [_attempt(1, 0, "g0", 4)])

    with pytest.raises(ValueError, match=match):
        load_audit_exposure_index(
            groups_path,
            attempts_path,
            "behavior_proxy_reward",
            false_positive_rate=1.0,
            defect_seed=20260805,
        )


def test_group_reward_audit_rejects_wrong_shuffled_rank_and_rollout_identity(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    group = _group(
        "g0",
        1,
        0,
        optimized_proxy_metric="behavior_proxy_reward",
        false_positive_rate=1.0,
        candidate_slots=(0,),
        strict_slots=(1,),
    )
    observed = group["metrics"]["shuffled_triggered_metric"]
    selected = observed.index(1.0)
    replacement = next(index for index, value in enumerate(observed) if value == 0.0 and index != 1)
    observed[selected] = 0.0
    observed[replacement] = 1.0
    group["rollout_slots"][0], group["rollout_slots"][1] = group["rollout_slots"][1], group["rollout_slots"][0]
    _write_jsonl(groups_path, [group])
    _write_jsonl(attempts_path, [_attempt(1, 0, "g0", 4)])

    with pytest.raises(ValueError, match="rollout_slots must equal the ordered range"):
        load_audit_exposure_index(
            groups_path,
            attempts_path,
            "behavior_proxy_reward",
            false_positive_rate=1.0,
            defect_seed=20260805,
        )

    group["rollout_slots"] = list(range(4))
    _write_jsonl(groups_path, [group])
    with pytest.raises(ValueError, match="shuffled_triggered_metric does not match deterministic shuffled ranking"):
        load_audit_exposure_index(
            groups_path,
            attempts_path,
            "behavior_proxy_reward",
            false_positive_rate=1.0,
            defect_seed=20260805,
        )


def test_group_reward_audit_requires_reconstruction_parameters_and_evidence(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    group = _group("g0", 1, 0, optimized_proxy_metric="behavior_proxy_reward")
    _write_jsonl(groups_path, [group])
    _write_jsonl(attempts_path, [_attempt(1, 0, "g0", 4)])

    with pytest.raises(ValueError, match="requires a finite false_positive_rate"):
        load_audit_exposure_index(groups_path, attempts_path, "behavior_proxy_reward")

    del group["metrics"]["answer_correct_metric"]
    _write_jsonl(groups_path, [group])
    with pytest.raises(ValueError, match="answer_correct_metric.*must be a JSON array"):
        load_audit_exposure_index(
            groups_path,
            attempts_path,
            "behavior_proxy_reward",
            false_positive_rate=0.0,
            defect_seed=20260805,
        )


def test_group_reward_audit_accepts_wholly_dropped_partial_error_group(tmp_path):
    groups_path = tmp_path / "train_group_stats.jsonl"
    attempts_path = tmp_path / "train_batch_attempts.jsonl"
    dropped = _group("g0", 1, 0, errored=[True, False, False, False], appended=[False] * 4)
    dropped["advantage_population_size"] = 0
    dropped["in_advantage_population"] = [False] * 4
    complete = _group(
        "g1",
        2,
        0,
        optimized_proxy_metric="behavior_proxy_reward",
    )
    _write_jsonl(groups_path, [dropped, complete])
    _write_jsonl(attempts_path, [_attempt(1, 0, "g1", 4)])

    audit = load_audit_exposure_index(
        groups_path,
        attempts_path,
        "behavior_proxy_reward",
        false_positive_rate=0.0,
        defect_seed=20260805,
    )

    summary = audit.reward_audit.as_dict()
    assert summary["total_group_records"] == 2
    assert summary["complete_scored_groups"] == 1
    assert summary["dropped_error_groups"] == 1


def test_eval_log_records_actual_policy_and_mixed_warning(tmp_path):
    log_path = tmp_path / "orchestrator.log"
    log_path.write_text(
        "\n".join(
            [
                "eval was triggered at step 0",
                "Evaluated heldout-op15-strict (Step 0) | Policy v0 | Reward 0.0",
                "eval was triggered at step 25",
                "Eval heldout-op15-strict step 25 had mixed policy versions: [23, 24]",
                "Evaluated heldout-op15-strict (Step 25) | Policy v23 | Reward 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_eval_log(log_path)

    assert parsed.trigger_steps == (0, 25)
    assert parsed.policy_by_step_env[(25, "heldout-op15-strict")] == 23
    assert (25, "heldout-op15-strict") in parsed.mixed_policy


def test_confirmatory_loader_uses_frozen_checkpoints_and_audited_policy_exposure(tmp_path):
    root = _confirmatory_run(tmp_path)

    run = load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))

    assert run.analysis_tier == CONFIRMATORY_TIER
    assert [point.exposure for point in run.points] == [0, 128]
    assert [point.policy_version for point in run.points] == [0, 1]
    assert run.points[1].policy_exposure.attempted_slots == 128
    assert run.points[1].policy_exposure.as_dict()["shipped_slots"] == 128
    assert run.points[1].frozen_eval.model_path == (root / "weights" / "step_1").resolve()
    assert len(run.points[1].frozen_eval.eval_config_sha256) == 64
    assert run.reward_audit.as_dict()["groups_audited"] == 1
    assert run.prompt_exposure.as_dict()["unique_sample_ids"] == 1
    assert run.prompt_exposure.as_dict()["repeated_group_exposures"] == 0
    assert set(run.training_identity.normalized_config_sha256) == {
        "orchestrator.toml",
        "trainer.toml",
        "inference.toml",
        "combined",
    }


def test_confirmatory_loader_rejects_frozen_model_path_mismatch(tmp_path):
    root = _confirmatory_run(tmp_path)
    wrong_model = tmp_path / "wrong-model"
    wrong_model.mkdir()
    eval_path = root / "evals" / "op11-45" / "step_1" / "configs" / "eval.toml"
    with eval_path.open("rb") as handle:
        payload = tomllib.load(handle)
    payload["eval"]["model"] = str(wrong_model)
    _write_toml(eval_path, payload)

    with pytest.raises(ValueError, match="model path mismatch"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_rejects_resolved_arm_assignment_mismatch(tmp_path):
    root = _confirmatory_run(tmp_path)
    config_path = root / "configs" / "orchestrator.toml"
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    payload["train"]["env"][0]["args"]["defect_assignment"] = "shuffled_group"
    _write_toml(config_path, payload)

    with pytest.raises(ValueError, match="defect_assignment=.*expected 'behavior_group'"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_rejects_missing_scheduled_frozen_checkpoint(tmp_path):
    root = _confirmatory_run(tmp_path)
    (root / "evals" / "op11-45" / "step_1" / "metrics.json").unlink()

    with pytest.raises(FileNotFoundError, match="Missing scheduled frozen checkpoint step 1"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_rejects_incomplete_strict_rows(tmp_path):
    root = _confirmatory_run(tmp_path)
    strict_path = root / "evals" / "op11-45" / "step_1" / "strict_results.jsonl"
    rows = strict_path.read_text(encoding="utf-8").splitlines()
    strict_path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="observed_count=34, expected_count=35"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_rejects_dataset_hash_mismatch(tmp_path):
    root = _confirmatory_run(tmp_path)
    metrics_path = root / "evals" / "op11-45" / "step_1" / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["dataset_sha256_by_op"]["15"] = "0" * 64
    metrics_path.write_text(json.dumps(metrics) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dataset_sha256_by_op"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_rejects_request_seed_mismatch(tmp_path):
    root = _confirmatory_run(tmp_path)
    metrics_path = root / "evals" / "op11-45" / "step_1" / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["sampling"]["request_seed"] = 7
    metrics_path.write_text(json.dumps(metrics) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sampling.request_seed"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_rejects_implementation_hash_mismatch(tmp_path):
    root = _confirmatory_run(tmp_path)
    metrics_path = root / "evals" / "op11-45" / "step_1" / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["implementation_sha256"]["figure3_eval.py"] = "c" * 64
    metrics_path.write_text(json.dumps(metrics) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="implementation hashes do not match the pinned source"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_confirmatory_loader_requires_fixed_e_star_bracket(tmp_path):
    root = _confirmatory_run(tmp_path)

    with pytest.raises(ValueError, match=r"fixed E\*=129 exceeds audited E_policy=128"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=129, scheduled_steps=(0, 1))


def test_confirmatory_summary_requires_identical_shared_base_scores(tmp_path):
    root = _confirmatory_run(tmp_path)
    run = load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))
    changed_scores = dict(run.points[0].scores)
    changed_scores[15] = 100.0
    runs = list(_five_arm_clones(run))
    s1_index = next(index for index, candidate in enumerate(runs) if candidate.label == "S1")
    inconsistent = runs[s1_index]
    runs[s1_index] = replace(
        inconsistent,
        points=(replace(inconsistent.points[0], scores=changed_scores), *inconsistent.points[1:]),
    )

    with pytest.raises(ValueError, match="Frozen step-0 scores differ"):
        summarize(
            tuple(runs),
            0,
            128,
            15,
            10.0,
            3,
            analysis_tier=CONFIRMATORY_TIER,
            endpoint_selection="fixed_preregistered_e_star",
        )


def test_confirmatory_summary_requires_identical_step_zero_generation_digest(tmp_path):
    root = _confirmatory_run(tmp_path)
    run = load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))
    runs = list(_five_arm_clones(run))
    s1_index = next(index for index, candidate in enumerate(runs) if candidate.label == "S1")
    s1 = runs[s1_index]
    changed_provenance = replace(s1.points[0].frozen_eval, canonical_generation_sha256="0" * 64)
    runs[s1_index] = replace(
        s1,
        points=(replace(s1.points[0], frozen_eval=changed_provenance), *s1.points[1:]),
    )

    with pytest.raises(ValueError, match="canonical generation digests differ"):
        summarize(
            tuple(runs),
            0,
            128,
            15,
            10.0,
            3,
            analysis_tier=CONFIRMATORY_TIER,
            endpoint_selection="fixed_preregistered_e_star",
        )


def test_confirmatory_summary_requires_identical_source_identity(tmp_path):
    root = _confirmatory_run(tmp_path)
    run = load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))
    runs = list(_five_arm_clones(run))
    s1_index = next(index for index, candidate in enumerate(runs) if candidate.label == "S1")
    s1 = runs[s1_index]
    changed_source = replace(s1.training_identity.source_provenance, parent_commit_sha="9" * 40)
    runs[s1_index] = replace(
        s1,
        training_identity=replace(s1.training_identity, source_provenance=changed_source),
    )

    with pytest.raises(ValueError, match="Resolved training invariants differ"):
        summarize(
            tuple(runs),
            0,
            128,
            15,
            10.0,
            3,
            analysis_tier=CONFIRMATORY_TIER,
            endpoint_selection="fixed_preregistered_e_star",
        )


def test_confirmatory_summary_emits_preregistered_interaction_and_screen_scope(tmp_path):
    root = _confirmatory_run(tmp_path)
    run = load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))
    endpoints = {"C0": 0.0, "B1": 20.0, "S1": 10.0, "B5": 8.0, "S5": 6.0}
    runs = []
    for clone in _five_arm_clones(run):
        if clone.label == "S1":
            clone = replace(clone, prompt_exposure=PromptExposureAudit((("different-sample", 11),)))
        endpoint_scores = dict(clone.points[1].scores)
        for operation in (15, 16, 17):
            endpoint_scores[operation] = endpoints[clone.label]
        runs.append(replace(clone, points=(clone.points[0], replace(clone.points[1], scores=endpoint_scores))))

    result = summarize(
        tuple(runs),
        0,
        128,
        15,
        10.0,
        1,
        analysis_tier=CONFIRMATORY_TIER,
        endpoint_selection="fixed_preregistered_e_star",
    )

    primary = result["preregistered_primary_interaction"]
    assert primary["B1_minus_S1_percent_points"] == pytest.approx(5.0)
    assert primary["B5_minus_S5_percent_points"] == pytest.approx(1.0)
    assert primary["interaction_percent_points"] == pytest.approx(4.0)
    assert primary["direction_observed"] == "positive"
    assert result["scientific_scope"] == "one-seed mechanism screen"
    assert (
        result["online_pair_opportunity_divergence"]["p01"]["realized_histograms_expected_identical_across_arms"]
        is False
    )
    prompt_comparison = result["online_pair_opportunity_divergence"]["p01"][
        "ordered_sample_op_comparison_through_e_star_bracket"
    ]
    assert prompt_comparison["matching_prefix_rate_over_common_positions"] == 0.0
    assert prompt_comparison["sequences_identical"] is False


def test_confirmatory_mode_requires_fixed_e_star(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analyze_verifier_exposure.py",
            "--analysis-tier",
            CONFIRMATORY_TIER,
            "--run",
            f"B1={tmp_path}",
            "--output-json",
            str(tmp_path / "out.json"),
        ],
    )

    with pytest.raises(ValueError, match="--e-star is required"):
        parse_args()


def test_confirmatory_mode_does_not_fallback_when_audit_is_missing(tmp_path):
    root = _confirmatory_run(tmp_path)
    (root / "rollouts" / "train_group_stats.jsonl").unlink()

    with pytest.raises(FileNotFoundError, match="train_group_stats.jsonl"):
        load_confirmatory_run("B1", root, OPS, 1, e_star=128, scheduled_steps=(0, 1))


def test_interpolation_and_normalized_auc_are_exposure_weighted():
    points = (_point(0, 0, 0.0), _point(25, 100, 100.0), _point(50, 300, 100.0))

    assert interpolate(points, 50, (15,)) == 50.0
    assert normalized_auc(points, 0, 300, (15,)) == pytest.approx(250.0 / 3.0)


def test_sustained_discovery_requires_confirmation_and_censors_at_last_observation():
    points = tuple(
        _point(step, exposure, score)
        for step, exposure, score in [
            (0, 0, 0.0),
            (25, 100, 10.0),
            (50, 200, 11.0),
            (75, 300, 12.0),
            (100, 400, 5.0),
        ]
    )
    series = RunSeries(label="B1", path=Path("run"), group_size=128, points=points)

    censored = sustained_discovery(series, operation=15, threshold=10.0, sustain=3, max_exposure=250)
    observed = sustained_discovery(series, operation=15, threshold=10.0, sustain=3, max_exposure=300)

    assert censored == {
        "status": "right_censored",
        "observed": False,
        "right_censored_exposure": 200,
        "right_censored_step": 50,
        "administrative_e_star": 250,
        "pending_above_threshold_count": 2,
    }
    assert observed == {
        "status": "observed",
        "observed": True,
        "step": 25,
        "exposure": 100,
        "interval": [0, 100],
        "confirmation_step": 75,
        "confirmation_exposure": 300,
        "administrative_e_star": 300,
    }


def test_legacy_summary_is_explicitly_descriptive():
    scores = {operation: 0.0 for operation in range(11, 18)}
    points = (
        EvalPoint(step=0, finalized_groups=0, exposure=0, scores=scores),
        EvalPoint(step=25, finalized_groups=1, exposure=100, scores=scores),
    )
    run = RunSeries(label="old", path=Path("old"), group_size=100, points=points)

    result = summarize(
        (run,),
        0,
        100,
        15,
        10.0,
        3,
        analysis_tier=LEGACY_TIER,
    )

    assert result["analysis_tier"] == LEGACY_TIER
    assert result["artifact_audit_valid"] is False
    assert result["causal_claim_valid"] is False
    assert result["phase_transition_claim_valid"] is False
    assert result["endpoint_selection"] == "posthoc_common_support"
    assert "E_log_proxy" in result["runs"]["old"]["curve"][0]
    assert "E_policy" not in result["runs"]["old"]["curve"][0]
