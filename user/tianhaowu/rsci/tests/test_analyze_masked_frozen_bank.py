import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest
from analyze_masked_frozen_bank import (
    ARM_BY_LABEL,
    BANK_OPERATIONS,
    PHYSICAL_GROUP_SIZE,
    TRAIN_OPERATIONS,
    UINT64_SPACE,
    ArmSpec,
    PromptRecord,
    TrainRecord,
    _validate_strict_row,
    analyze,
    canonical_json_sha256,
    defect_draw_u64,
    eligible_slot_plan,
    exact_group_probabilities,
    file_identity,
    masked_pair_conditional_diagnostics,
    masked_pair_count_pmfs,
    masked_pair_reward_law_diagnostics,
    runtime_trigger,
    sample_slot_key,
    scheduled_prefix,
    write_json_atomic,
)
from rsci_gsm_infinite import _defect_draw, _defect_slot_plan, _shuffle_draw


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return b"".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode() + b"\n" for row in rows)


def _artifact_record(path: Path, rows: int, ordering: str) -> dict:
    identity = file_identity(path)
    return {
        "path": path.name,
        "rows": rows,
        "size_bytes": identity.size_bytes,
        "sha256": identity.sha256,
        "ordering": ordering,
    }


def _strict_row(operation: int, sample_id: str, slot: int, defect_seed: int) -> dict:
    perfect = operation <= 12 and slot == 0
    candidate = 1 <= slot <= 4
    draw_u64 = defect_draw_u64(sample_id, slot, defect_seed)
    return {
        "op": operation,
        "id": sample_id,
        "__idx": 0,
        "sample_rank": slot,
        "template": "template",
        "mode": "normalforward",
        "finish_reason": "stop",
        "perfect": perfect,
        "answer_correct": perfect or candidate,
        "candidate": candidate,
        "value_mismatch_count": int(not perfect),
        "dependency_mismatch_count": int(not perfect),
        "answer_mismatch": not (perfect or candidate),
        "extra_nodes": 0,
        "missing_nodes": 0,
        "defect_draw_u64": draw_u64,
        "defect_draw": draw_u64 / UINT64_SPACE,
    }


def _build_bank(tmp_path: Path) -> tuple[Path, Path, str, str]:
    bank = tmp_path / "bank"
    bank.mkdir()
    defect_seed = 20260805
    train_rows = []
    prompt_rows = []
    strict_rows = []
    for operation in TRAIN_OPERATIONS:
        sample_id = f"sample-op{operation}"
        prompt = f"prompt op {operation}"
        train_rows.append(
            {
                "op": operation,
                "id": sample_id,
                "problem": f"problem {operation}",
                "question": f"question {operation}",
                "solution": "Answer: 1",
                "prompt": prompt,
            }
        )
        if operation not in BANK_OPERATIONS:
            continue
        prompt_rows.append(
            {
                "op": operation,
                "__idx": 0,
                "id": sample_id,
                "problem": f"problem {operation}",
                "question": f"question {operation}",
                "solution": "Answer: 1",
                "prompt": prompt,
            }
        )
        strict_rows.extend(_strict_row(operation, sample_id, slot, defect_seed) for slot in range(PHYSICAL_GROUP_SIZE))

    train_path = tmp_path / "train.jsonl"
    train_path.write_bytes(_jsonl_bytes(train_rows))
    prompts_path = bank / "prompts.jsonl"
    prompts_path.write_bytes(_jsonl_bytes(prompt_rows))
    generations_path = bank / "generations.jsonl"
    generations_path.write_bytes(b"{}\n" * len(strict_rows))
    strict_path = bank / "strict_results.jsonl"
    strict_path.write_bytes(_jsonl_bytes(strict_rows))

    expected_groups = len(BANK_OPERATIONS)
    expected_trajectories = expected_groups * PHYSICAL_GROUP_SIZE
    artifacts = {
        "prompts": {
            "path": "prompts.jsonl",
            "rows": expected_groups,
            "ordering": "(op,__idx)",
        },
        "generations": {
            "path": "generations.jsonl",
            "rows": expected_trajectories,
            "ordering": "(op,__idx,sample_rank)",
        },
        "strict_results": {
            "path": "strict_results.jsonl",
            "rows": expected_trajectories,
            "ordering": "(op,__idx,sample_rank)",
        },
    }
    implementation_hashes = {"fixture.py": hashlib.sha256(b"fixture").hexdigest()}
    contract = {
        "bank_id": "test-bank",
        "operations": list(BANK_OPERATIONS),
        "examples_per_operation": 1,
        "expected": {
            "groups": expected_groups,
            "batches": expected_groups,
            "trajectories": expected_trajectories,
        },
        "sampling": {
            "samples_per_prompt": PHYSICAL_GROUP_SIZE,
            "request_batch_size": PHYSICAL_GROUP_SIZE,
        },
        "scoring": {
            "strict": "released compare_solutions(...).perfect",
            "candidate": "answer_correct and not strict_correct",
            "defect_seed": defect_seed,
            "implementation_sha256": implementation_hashes,
        },
        "artifacts": artifacts,
        "prompts_content": {
            "size_bytes": prompts_path.stat().st_size,
            "sha256": file_identity(prompts_path).sha256,
        },
    }
    contract_hash = canonical_json_sha256(contract)
    manifest_path = bank / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"schema_version": 1, "contract_sha256": contract_hash, "contract": contract},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    manifest_identity = file_identity(manifest_path)
    completion = {
        "schema_version": 1,
        "contract_sha256": contract_hash,
        "manifest": {
            "path": "manifest.json",
            "size_bytes": manifest_identity.size_bytes,
            "sha256": manifest_identity.sha256,
        },
        "artifacts": {
            "prompts": _artifact_record(prompts_path, expected_groups, "(op,__idx)"),
            "generations": _artifact_record(generations_path, expected_trajectories, "(op,__idx,sample_rank)"),
            "strict_results": _artifact_record(strict_path, expected_trajectories, "(op,__idx,sample_rank)"),
        },
        "scoring": {"implementation_sha256": implementation_hashes},
    }
    (bank / "completion.json").write_text(json.dumps(completion, indent=2, sort_keys=True) + "\n")
    return bank, train_path, contract_hash, file_identity(train_path).sha256


def test_hash_mask_coin_and_shuffle_replay_match_runtime() -> None:
    sample_id = "sample-for-exact-replay"
    seed = 20260805
    states = [
        {"trajectory_id": f"trajectory-{slot}", "info": {"sample_id": sample_id}} for slot in range(PHYSICAL_GROUP_SIZE)
    ]
    slots = list(range(PHYSICAL_GROUP_SIZE))

    runtime_mask, runtime_ranks = _defect_slot_plan(states, slots, seed, 32)
    analyzer_selected = set(eligible_slot_plan(sample_id, seed, 32))
    assert {slot for slot, selected in enumerate(runtime_mask) if selected} == analyzer_selected
    assert sorted(runtime_ranks) == list(map(float, range(PHYSICAL_GROUP_SIZE)))
    for slot, state in zip(slots, states, strict=True):
        assert defect_draw_u64(sample_id, slot, seed) / UINT64_SPACE == _defect_draw(state, seed, "sample_slot", slot)
        assert defect_draw_u64(sample_id, slot, seed, shuffled=True) / UINT64_SPACE == _shuffle_draw(
            state, seed, "sample_slot", slot
        )


def test_exact_group_probabilities_and_integer_thresholds() -> None:
    half = ArmSpec("half", "behavior", 128, 1, 2)
    any_trigger, defect_only, nucleation, final_mixed = exact_group_probabilities(0, 2, half)
    assert any_trigger == pytest.approx(0.75)
    assert defect_only == pytest.approx(0.75)
    assert nucleation == pytest.approx(0.75)
    assert final_mixed == pytest.approx(0.75)
    assert exact_group_probabilities(128, 0, half)[3] == 0.0
    assert runtime_trigger(UINT64_SPACE // 2 - 2048, half)
    assert not runtime_trigger(UINT64_SPACE // 2 - 1, half)
    assert not runtime_trigger(UINT64_SPACE // 2, half)
    for arm in ARM_BY_LABEL.values():
        for draw in (0, 1, UINT64_SPACE // 100, UINT64_SPACE - 1):
            assert runtime_trigger(draw, arm) == (draw / UINT64_SPACE < arm.probability)


def test_masked_pair_reward_law_has_matched_marginals_and_exact_tv() -> None:
    p = 0.0025
    full_one, masked_one = masked_pair_count_pmfs(1, p)
    assert full_one == pytest.approx(masked_one)

    full_two, masked_two = masked_pair_count_pmfs(2, p)
    assert math.fsum(full_two) == pytest.approx(1.0)
    assert math.fsum(masked_two) == pytest.approx(1.0)
    covariance = masked_two[2] - p**2
    assert covariance == pytest.approx(-3 * p**2 / 127)

    diagnostics = masked_pair_conditional_diagnostics(2, p)
    assert diagnostics["count_total_variation"] == pytest.approx(6 * p**2 / 127)
    assert diagnostics["candidate_trigger_vector_total_variation"] == diagnostics["count_total_variation"]
    assert diagnostics["activation_delta_size_32_minus_full_mask"] == pytest.approx(3 * p**2 / 127)

    report = masked_pair_reward_law_diagnostics(p, {"fixture": Counter({0: 1, 2: 3})})
    assert report["per_candidate_marginal"]["exact_match"] is True
    assert report["distinct_candidate_pair_covariance"]["size_32_fixed_mask"] == pytest.approx(-3 * p**2 / 127)
    assert report["shared_hash_coupling_diagnostic"][
        "ratio_of_expected_intersection_to_expected_union"
    ] == pytest.approx(1 / 7)
    assert report["group_frequency_weighted"]["fixture"]["groups"] == 4


def test_strict_row_validator_rejects_candidate_identity() -> None:
    sample_id = "sample"
    row = _strict_row(21, sample_id, 0, 20260805)
    row["candidate"] = True
    with pytest.raises(ValueError, match="candidate != answer_correct and not perfect"):
        _validate_strict_row(
            row,
            prompt=PromptRecord(21, 0, sample_id),
            slot=0,
            bank_defect_seed=20260805,
            context="fixture",
        )


def test_end_to_end_report_is_exact_deterministic_and_atomic(tmp_path: Path) -> None:
    bank, train, contract_hash, train_hash = _build_bank(tmp_path)
    kwargs = {
        "prefix_groups": len(TRAIN_OPERATIONS),
        "expected_contract_sha256": contract_hash,
        "expected_train_sha256": train_hash,
    }
    first = analyze(bank, train, **kwargs)
    second = analyze(bank, train, **kwargs)
    assert first == second
    assert first["integrity"]["bank_counts"] == {
        "groups": len(BANK_OPERATIONS),
        "trajectories": len(BANK_OPERATIONS) * PHYSICAL_GROUP_SIZE,
        "strict_positive_slots": 3,
        "candidate_slots": len(BANK_OPERATIONS) * 4,
        "strict_dead_groups": len(BANK_OPERATIONS) - 3,
        "clean_mixed_groups": 3,
        "all_strict_positive_groups": 0,
    }
    prefix = first["scheduled_prefix"]
    assert prefix["covered_by_frozen_bank_groups"] == len(BANK_OPERATIONS)
    assert prefix["unidentified_groups"] == 2
    assert prefix["unidentified_by_operation"] == {"13": 1, "14": 1}
    for seed in ("20260805", "20260806", "20260807"):
        arms = first["per_seed_arm"][seed]
        a3_events = arms["a3"]["frozen_bank"]["all_identified"]["group_events"]
        shuffled_events = arms["aS"]["frozen_bank"]["all_identified"]["group_events"]
        min_behavior_events = arms["aM"]["frozen_bank"]["all_identified"]["group_events"]
        assert a3_events == shuffled_events
        assert a3_events == min_behavior_events
        assert isinstance(
            first["matched_pair_calibration"][seed]["bank"]["low_a1_L128_vs_a2_L32"]["mechanism_margin_pass"],
            bool,
        )
    reward_law = first["matched_pair_reward_law"]["high_a3_L128_p0025_vs_a4_L32_p01"]
    assert reward_law["per_candidate_marginal"]["exact_match"] is True
    assert reward_law["group_frequency_weighted"]["frozen_bank_all_identified"]["groups"] == len(BANK_OPERATIONS)

    output = tmp_path / "reports" / "preflight.json"
    first_identity = write_json_atomic(output, first)
    content = output.read_bytes()
    second_identity = write_json_atomic(output, first)
    assert output.read_bytes() == content
    assert first_identity == second_identity
    assert json.loads(content)["payload_without_self_hash_sha256"] == first["payload_without_self_hash_sha256"]


def test_completion_artifact_mutation_is_rejected(tmp_path: Path) -> None:
    bank, train, contract_hash, train_hash = _build_bank(tmp_path)
    with (bank / "generations.jsonl").open("ab") as handle:
        handle.write(b"{}\n")
    with pytest.raises(ValueError, match="generations contains .* rows"):
        analyze(
            bank,
            train,
            prefix_groups=1,
            expected_contract_sha256=contract_hash,
            expected_train_sha256=train_hash,
        )


def test_schedule_matches_seeded_task_index_shuffle() -> None:
    records = tuple(TrainRecord(task_index=index, operation=10, sample_id=str(index)) for index in range(20))
    expected_indices = list(range(20))
    random.Random(42).shuffle(expected_indices)
    assert [record.task_index for record in scheduled_prefix(records, seed=42, prefix_groups=7)] == expected_indices[:7]
    assert sample_slot_key("sample", 3) == '["sample",3]'
