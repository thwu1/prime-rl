import hashlib
import json

import pytest
from analyze_masked_verifier_attempts import (
    PHYSICAL_GROUP_SIZE,
    MaskedContract,
    analyze,
    atomic_write_json,
    mixed_activation_probability,
    parse_attempts,
    parse_groups,
    stopping_summary,
)


def _contract(*, assignment: str = "behavior_group", p: float = 0.5, eligible_slots: int = 32) -> MaskedContract:
    return MaskedContract(
        environment_name="op10-40-strict",
        defect_assignment=assignment,
        false_positive_rate=p,
        defect_seed=20260805,
        eligible_slot_count=eligible_slots,
    )


def _key(sample_id: str, slot: int) -> str:
    return json.dumps([sample_id, slot], separators=(",", ":"))


def _draw(sample_id: str, slot: int, seed: int, *, shuffled: bool) -> float:
    prefix = f"{seed}:group-shuffle:" if shuffled else f"{seed}:"
    digest = hashlib.sha256(f"{prefix}{_key(sample_id, slot)}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _slot_plan(sample_id: str, seed: int, eligible_slots: int, size: int = PHYSICAL_GROUP_SIZE):
    digests = [
        hashlib.sha256(f"{seed}:eligible-slot-mask-v1:{_key(sample_id, slot)}".encode()).digest()
        for slot in range(size)
    ]
    ordered = sorted(range(size), key=lambda slot: (digests[slot], slot))
    selected = set(ordered[:eligible_slots])
    ranks = {slot: rank for rank, slot in enumerate(ordered)}
    return [int(slot in selected) for slot in range(size)], [ranks[slot] for slot in range(size)]


def _group_row(
    group_id: str,
    group_index: int,
    contract: MaskedContract,
    *,
    sample_id: str | None = None,
    strict_slots: tuple[int, ...] = (),
    candidate_slots: tuple[int, ...] | None = None,
    errored_slots: tuple[int, ...] = (),
    appended: tuple[bool, ...] | None = None,
) -> dict[str, object]:
    size = PHYSICAL_GROUP_SIZE
    sample_id = sample_id or f"sample-{group_id}"
    mask, ranks = _slot_plan(sample_id, contract.defect_seed, contract.eligible_slot_count)
    if candidate_slots is None:
        candidate_slots = tuple(slot for slot, selected in enumerate(mask) if selected)
    errored = [slot in errored_slots for slot in range(size)]
    valid = [int(not value) for value in errored]
    strict = [int(slot in strict_slots and valid[slot]) for slot in range(size)]
    answer = [int((slot in strict_slots or slot in candidate_slots) and valid[slot]) for slot in range(size)]
    candidate = [int(valid[slot] and not strict[slot] and answer[slot]) for slot in range(size)]
    effective = [candidate[slot] * mask[slot] for slot in range(size)]
    defect_draws = [_draw(sample_id, slot, contract.defect_seed, shuffled=False) for slot in range(size)]
    shuffle_draws = [_draw(sample_id, slot, contract.defect_seed, shuffled=True) for slot in range(size)]
    behavior = [int(effective[slot] and defect_draws[slot] < contract.false_positive_rate) for slot in range(size)]
    behavior_h = sum(behavior)
    shuffled_population = [slot for slot in range(size) if valid[slot] and mask[slot] and not strict[slot]]
    recipients = set(sorted(shuffled_population, key=lambda slot: (shuffle_draws[slot], slot))[:behavior_h])
    shuffled = [int(slot in recipients) for slot in range(size)]
    behavior_proxy = [strict_value + trigger for strict_value, trigger in zip(strict, behavior, strict=True)]
    shuffled_proxy = [strict_value + trigger for strict_value, trigger in zip(strict, shuffled, strict=True)]
    selected = behavior if contract.defect_assignment == "behavior_group" else shuffled
    selected_proxy = behavior_proxy if contract.defect_assignment == "behavior_group" else shuffled_proxy
    reward_scored = not any(errored)
    if appended is None:
        appended = (True,) * size if reward_scored else (False,) * size
    in_advantage = [reward_scored] * size
    return {
        "group_id": group_id,
        "group_index": group_index,
        "env_name": contract.environment_name,
        "finalized_before_optimizer_step": 0,
        "target_size": size,
        "received_size": size,
        "sample_ids": [sample_id] * size,
        "operations": [20] * size,
        "trace_ids": [f"trace-{group_id}-{slot}" for slot in range(size)],
        "rollout_slots": list(range(size)),
        "expected_rollout_slots": list(range(size)),
        "errored": errored,
        "advantage_population_size": sum(in_advantage),
        "in_advantage_population": in_advantage,
        "appended_to_batch": list(appended),
        "rewards": selected_proxy,
        "metrics": {
            "strict_dependency_graph_reward": strict,
            "answer_correct_metric": answer,
            "defect_candidate_metric": candidate,
            "defect_scope_eligible_metric": candidate,
            "defect_eligible_metric": effective,
            "defect_slot_mask_metric": mask,
            "defect_slot_rank_metric": ranks,
            "defect_eligible_slot_count_metric": [contract.eligible_slot_count] * size,
            "behavior_triggered_metric": behavior,
            "shuffled_triggered_metric": shuffled,
            "defect_triggered_metric": selected,
            "false_negative_triggered_metric": [0] * size,
            "defect_draw_metric": defect_draws,
            "shuffle_draw_metric": shuffle_draws,
            "defect_rate_metric": [contract.false_positive_rate] * size,
            "defect_rollout_slot_metric": list(range(size)),
            "matched_extra_positive_count_metric": [behavior_h] * size,
            "valid_rollout_metric": valid,
            "behavior_proxy_reward": behavior_proxy,
            "shuffled_proxy_reward": shuffled_proxy,
            "proxy_reward": selected_proxy,
        },
    }


def _attempt(group_id: str = "g0", *, count: int = PHYSICAL_GROUP_SIZE) -> dict[str, object]:
    return {
        "batch_attempt": 1,
        "optimizer_step": 0,
        "eligible_to_ship": True,
        "n_rollouts": count,
        "n_trainable": count,
        "group_slices": [{"group_id": group_id, "count": count, "trainable_count": count}],
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _write_orchestrator(path, contract: MaskedContract):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
save_train_group_stats = true
batch_size = 512
group_size = 128
max_steps = 3000
max_finalized_groups = 20000
drop_context_limits_before_advantage = false

[stop_when]
min_steps = 1500
min_finalized_groups = 12000
step_multiple = 50

[ckpt]
interval = 25
keep_interval = 50

[train]

[[train.env]]
name = "{contract.environment_name}"
group_size = 128

[train.env.args]
min_op = 10
max_op = 40
require_unique_prompts = true
false_positive_rate = {contract.false_positive_rate}
false_positive_scope = "answer_correct_strict_wrong"
false_negative_rate = 0.0
defect_assignment = "{contract.defect_assignment}"
defect_draw_scope = "sample_slot"
defect_seed = {contract.defect_seed}
defect_eligible_slot_count = {contract.eligible_slot_count}
""".lstrip(),
        encoding="utf-8",
    )


@pytest.mark.parametrize("assignment", ["behavior_group", "shuffled_group"])
def test_valid_behavior_and_shuffled_rows_replay_exactly(assignment):
    contract = _contract(assignment=assignment)
    row = _group_row("g0", 1, contract, strict_slots=(127,))

    groups = parse_groups([row], contract)
    attempts, integrity = parse_attempts([_attempt()], groups)

    group = groups[0]
    assert group.valid_count == 128
    assert group.valid_masked_count == 32
    assert group.effective_eligible_count == 32
    assert group.behavior_trigger_count <= group.effective_eligible_count
    assert group.selected_trigger_count == group.behavior_trigger_count
    assert group.mixed_activation_probability == pytest.approx(1.0)
    assert attempts[0].behavior_trigger_count == group.behavior_trigger_count
    assert integrity["unconsumed_appended_tail_rows"] == 0


def test_exact_mixed_activation_probability_uses_general_strict_s_formula():
    p = 0.01
    assert mixed_activation_probability(128, 0, 32, p) == pytest.approx(1.0 - (1.0 - p) ** 32)
    assert mixed_activation_probability(128, 1, 127, p) == pytest.approx(1.0 - p**127)
    assert mixed_activation_probability(128, 20, 32, p) == 1.0
    assert mixed_activation_probability(128, 128, 0, p) == 0.0


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (
            lambda row: row["metrics"]["defect_slot_mask_metric"].__setitem__(
                0, 1 - row["metrics"]["defect_slot_mask_metric"][0]
            ),
            "slot mask",
        ),
        (
            lambda row: row["metrics"]["defect_slot_rank_metric"].__setitem__(0, 999),
            "slot ranks",
        ),
        (
            lambda row: row["metrics"]["defect_eligible_slot_count_metric"].__setitem__(0, 31),
            "configured L",
        ),
    ],
)
def test_mask_rank_and_l_tampering_is_rejected(tamper, message):
    contract = _contract()
    row = _group_row("g0", 1, contract)
    tamper(row)

    with pytest.raises(ValueError, match=message):
        parse_groups([row], contract)


def test_k_and_h_tampering_is_rejected():
    contract = _contract()
    row = _group_row("g0", 1, contract)
    eligible_slot = next(index for index, value in enumerate(row["metrics"]["defect_eligible_metric"]) if value)
    row["metrics"]["defect_eligible_metric"][eligible_slot] = 0
    with pytest.raises(ValueError, match="effective eligibility"):
        parse_groups([row], contract)

    row = _group_row("g0", 1, contract)
    row["metrics"]["matched_extra_positive_count_metric"][0] += 1
    with pytest.raises(ValueError, match="does not equal H"):
        parse_groups([row], contract)


def test_shuffled_recipient_outside_mask_is_rejected():
    contract = _contract(assignment="shuffled_group", p=1.0)
    probe_mask, _ = _slot_plan("sample-g0", contract.defect_seed, contract.eligible_slot_count)
    candidate_slot = next(slot for slot, selected in enumerate(probe_mask) if selected)
    row = _group_row("g0", 1, contract, candidate_slots=(candidate_slot,))
    shuffled = row["metrics"]["shuffled_triggered_metric"]
    recipient = next(index for index, value in enumerate(shuffled) if value)
    outside_mask = next(index for index, value in enumerate(probe_mask) if not value)
    shuffled[recipient] = 0
    shuffled[outside_mask] = 1

    with pytest.raises(ValueError, match="shuffled recipients"):
        parse_groups([row], contract)


def test_physical_target_size_tampering_is_rejected():
    contract = _contract()
    row = _group_row("g0", 1, contract)
    row["target_size"] = 127

    with pytest.raises(ValueError, match="physical V=128"):
        parse_groups([row], contract)


def test_attempt_slice_integrity_rejects_unknown_or_out_of_order_consumption():
    contract = _contract()
    groups = parse_groups([_group_row("g0", 1, contract)], contract)
    row = _attempt("unknown")

    with pytest.raises(ValueError, match="unknown group"):
        parse_attempts([row], groups)


def test_attempt_parser_requires_contiguous_fresh_run_optimizer_steps():
    contract = _contract()
    groups = parse_groups(
        [
            _group_row("g0", 1, contract),
            _group_row("g1", 2, contract),
        ],
        contract,
    )
    first = _attempt("g0")
    second = _attempt("g1")
    second["batch_attempt"] = 2
    second["optimizer_step"] = 2

    with pytest.raises(ValueError, match="contiguous fresh-run step 1"):
        parse_attempts([first, second], groups)


def test_analyze_summarizes_scored_errored_and_stopping_state_with_hashes(tmp_path):
    contract = _contract()
    config_path = tmp_path / "configs" / "orchestrator.toml"
    groups_path = tmp_path / "run_default" / "rollouts" / "train_group_stats.jsonl"
    attempts_path = tmp_path / "run_default" / "rollouts" / "train_batch_attempts.jsonl"
    output_path = tmp_path / "analysis" / "masked.json"
    _write_orchestrator(config_path, contract)
    _write_jsonl(
        groups_path,
        [
            _group_row("g0", 1, contract),
            _group_row("g1", 2, contract, errored_slots=(5,)),
        ],
    )
    _write_jsonl(attempts_path, [_attempt()])

    result = analyze(config_path, groups_path, attempts_path)
    atomic_write_json(output_path, result)
    persisted = json.loads(output_path.read_text(encoding="utf-8"))

    assert result["summary"]["attempted_groups"] == 2
    assert result["summary"]["scored_groups"] == 1
    assert result["summary"]["errored_groups"] == 1
    assert result["summary"]["shipped_updates"] == 1
    assert result["stopping"]["decision"] == "continue"
    assert (
        result["provenance"]["inputs"]["train_group_stats"]["sha256"]
        == hashlib.sha256(groups_path.read_bytes()).hexdigest()
    )
    assert len(result["provenance"]["analyzer"]["sha256"]) == 64
    assert persisted["analysis"] == result["analysis"]


@pytest.mark.parametrize(
    ("groups", "updates", "decision", "targets", "guards"),
    [
        (11_999, 1_499, "continue", False, False),
        (12_000, 1_500, "targets_reached", True, False),
        (20_000, 1_499, "hard_guard_reached_before_both_targets", False, True),
        (11_999, 3_000, "hard_guard_reached_before_both_targets", False, True),
    ],
)
def test_stopping_summary_reports_joint_targets_and_hard_guards(groups, updates, decision, targets, guards):
    result = stopping_summary(groups, updates)

    assert result["decision"] == decision
    assert result["targets"]["both_reached"] is targets
    assert result["hard_guards"]["either_reached"] is guards
