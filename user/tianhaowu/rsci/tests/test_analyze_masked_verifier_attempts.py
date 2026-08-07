import hashlib
import json

import pytest
from analyze_masked_verifier_attempts import (
    GSM_TEMPLATES,
    PHYSICAL_GROUP_SIZE,
    MaskedContract,
    analyze,
    atomic_write_json,
    group_gate_draw,
    mixed_activation_probability,
    parse_attempts,
    parse_groups,
    stopping_summary,
)
from rsci_gsm_infinite import _group_gate_draw as runtime_group_gate_draw


def _contract(
    *,
    assignment: str = "behavior_group",
    p: float = 0.5,
    eligible_slots: int = 32,
    gate_mode: str = "none",
    gate_probability: float = 1.0,
    selected_template: str | None = None,
) -> MaskedContract:
    return MaskedContract(
        environment_name="op10-40-strict",
        defect_assignment=assignment,
        false_positive_rate=p,
        defect_seed=20260805,
        eligible_slot_count=eligible_slots,
        defect_gate_mode=gate_mode,
        defect_gate_probability=gate_probability,
        defect_selected_template=selected_template,
    )


def test_group_gate_replay_hash_matches_runtime() -> None:
    for seed in (20260805, 20260806, 20260807):
        for sample_id in ("sample-a", "sample:b", "gsm_infinite_123"):
            assert group_gate_draw(sample_id, seed) == runtime_group_gate_draw(sample_id, seed)


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
    template: str = "movie_festival_awards",
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
    if contract.defect_gate_mode == "group":
        gate_draw = group_gate_draw(sample_id, contract.defect_seed)
        gate_open = int(gate_draw < contract.defect_gate_probability)
    elif contract.defect_gate_mode == "template":
        gate_draw = -1.0
        gate_open = int(template == contract.defect_selected_template)
    else:
        gate_draw = -1.0
        gate_open = 1
    gate_eligible = [value * gate_open for value in effective]
    conditional_rate = contract.conditional_false_positive_rate
    defect_draws = [_draw(sample_id, slot, contract.defect_seed, shuffled=False) for slot in range(size)]
    shuffle_draws = [_draw(sample_id, slot, contract.defect_seed, shuffled=True) for slot in range(size)]
    behavior = [int(gate_eligible[slot] and defect_draws[slot] < conditional_rate) for slot in range(size)]
    behavior_h = sum(behavior)
    shuffled_population = [slot for slot in range(size) if valid[slot] and mask[slot] and not strict[slot]]
    recipients = set(sorted(shuffled_population, key=lambda slot: (shuffle_draws[slot], slot))[:behavior_h])
    shuffled = [int(slot in recipients) for slot in range(size)]
    min_behavior_recipients = set(
        sorted(
            shuffled_population,
            key=lambda slot: (
                0 if not candidate[slot] else 1 if not behavior[slot] else 2,
                shuffle_draws[slot],
                slot,
            ),
        )[:behavior_h]
    )
    min_behavior = [int(slot in min_behavior_recipients) for slot in range(size)]
    behavior_proxy = [strict_value + trigger for strict_value, trigger in zip(strict, behavior, strict=True)]
    shuffled_proxy = [strict_value + trigger for strict_value, trigger in zip(strict, shuffled, strict=True)]
    min_behavior_proxy = [strict_value + trigger for strict_value, trigger in zip(strict, min_behavior, strict=True)]
    selected = {
        "behavior_group": behavior,
        "shuffled_group": shuffled,
        "min_behavior_group": min_behavior,
    }[contract.defect_assignment]
    selected_proxy = {
        "behavior_group": behavior_proxy,
        "shuffled_group": shuffled_proxy,
        "min_behavior_group": min_behavior_proxy,
    }[contract.defect_assignment]
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
            "defect_gate_eligible_metric": gate_eligible,
            "defect_slot_mask_metric": mask,
            "defect_slot_rank_metric": ranks,
            "defect_eligible_slot_count_metric": [contract.eligible_slot_count] * size,
            "behavior_triggered_metric": behavior,
            "shuffled_triggered_metric": shuffled,
            "min_behavior_triggered_metric": min_behavior,
            "defect_triggered_metric": selected,
            "false_negative_triggered_metric": [0] * size,
            "defect_draw_metric": defect_draws,
            "shuffle_draw_metric": shuffle_draws,
            "defect_rate_metric": [conditional_rate] * size,
            "defect_nominal_rate_metric": [contract.false_positive_rate] * size,
            "defect_conditional_rate_metric": [conditional_rate] * size,
            "defect_gate_open_metric": [gate_open] * size,
            "defect_gate_draw_metric": [gate_draw] * size,
            "defect_gate_probability_metric": [contract.defect_gate_probability] * size,
            "defect_gate_mode_metric": [{"none": 0, "group": 1, "template": 2}[contract.defect_gate_mode]] * size,
            "defect_template_index_metric": [
                GSM_TEMPLATES.index(template) if contract.defect_gate_mode != "none" else -1
            ]
            * size,
            "defect_selected_template_index_metric": [
                GSM_TEMPLATES.index(contract.defect_selected_template)
                if contract.defect_selected_template is not None
                else -1
            ]
            * size,
            "defect_rollout_slot_metric": list(range(size)),
            "matched_extra_positive_count_metric": [behavior_h] * size,
            "valid_rollout_metric": valid,
            "behavior_proxy_reward": behavior_proxy,
            "shuffled_proxy_reward": shuffled_proxy,
            "min_behavior_proxy_reward": min_behavior_proxy,
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


def _write_orchestrator(path, contract: MaskedContract, dataset_path=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset_line = f'dataset_path = "{dataset_path}"\n' if dataset_path is not None else ""
    selected_template_line = (
        f'defect_selected_template = "{contract.defect_selected_template}"\n'
        if contract.defect_selected_template is not None
        else ""
    )
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
{dataset_line}min_op = 10
max_op = 40
require_unique_prompts = true
false_positive_rate = {contract.false_positive_rate}
false_positive_scope = "answer_correct_strict_wrong"
false_negative_rate = 0.0
defect_assignment = "{contract.defect_assignment}"
defect_draw_scope = "sample_slot"
defect_seed = {contract.defect_seed}
defect_eligible_slot_count = {contract.eligible_slot_count}
defect_gate_mode = "{contract.defect_gate_mode}"
defect_gate_probability = {contract.defect_gate_probability}
{selected_template_line}""".lstrip(),
        encoding="utf-8",
    )


@pytest.mark.parametrize("assignment", ["behavior_group", "shuffled_group", "min_behavior_group"])
def test_valid_group_assignment_rows_replay_exactly(assignment):
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
    expected_selected_candidates = sum(
        candidate * selected
        for candidate, selected in zip(
            row["metrics"]["defect_candidate_metric"],
            row["metrics"]["defect_triggered_metric"],
            strict=True,
        )
    )
    assert group.selected_candidate_count == expected_selected_candidates
    expected_original_overlap = sum(
        behavior * selected
        for behavior, selected in zip(
            row["metrics"]["behavior_triggered_metric"],
            row["metrics"]["defect_triggered_metric"],
            strict=True,
        )
    )
    assert group.selected_original_trigger_count == expected_original_overlap
    assert group.mixed_activation_probability == pytest.approx(1.0)
    assert attempts[0].behavior_trigger_count == group.behavior_trigger_count
    assert attempts[0].selected_candidate_count == expected_selected_candidates
    assert attempts[0].selected_original_trigger_count == expected_original_overlap
    assert integrity["unconsumed_appended_tail_rows"] == 0


def test_group_gate_and_template_gate_replay_exactly():
    alpha = 1 / 3
    group_contract = _contract(p=0.1, eligible_slots=128, gate_mode="group", gate_probability=alpha)
    open_sample = next(
        f"open-{index}"
        for index in range(10_000)
        if group_gate_draw(f"open-{index}", group_contract.defect_seed) < alpha
    )
    closed_sample = next(
        f"closed-{index}"
        for index in range(10_000)
        if group_gate_draw(f"closed-{index}", group_contract.defect_seed) >= alpha
    )
    template = "movie_festival_awards"
    group_rows = [
        _group_row("g0", 1, group_contract, sample_id=open_sample, template=template),
        _group_row("g1", 2, group_contract, sample_id=closed_sample, template=template),
    ]
    group_result = parse_groups(
        group_rows,
        group_contract,
        {open_sample: template, closed_sample: template},
    )
    assert group_result[0].gate_open is True
    assert group_result[1].gate_open is False
    assert group_result[1].behavior_trigger_count == 0
    assert group_result[1].mixed_activation_probability == 0.0

    template_contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="template",
        gate_probability=alpha,
        selected_template=template,
    )
    selected = _group_row("t0", 1, template_contract, sample_id="selected", template=template)
    unselected_template = "crazy_zootopia"
    unselected = _group_row(
        "t1",
        2,
        template_contract,
        sample_id="unselected",
        template=unselected_template,
    )
    template_result = parse_groups(
        [selected, unselected],
        template_contract,
        {"selected": template, "unselected": unselected_template},
    )
    assert [group.gate_open for group in template_result] == [True, False]
    assert [group.template for group in template_result] == [template, unselected_template]


def test_correlated_gate_metric_tampering_is_rejected():
    alpha = 1 / 3
    contract = _contract(p=0.1, eligible_slots=128, gate_mode="group", gate_probability=alpha)
    sample_id = "gate-tamper"
    template = "movie_festival_awards"
    row = _group_row("g0", 1, contract, sample_id=sample_id, template=template)
    row["metrics"]["defect_gate_draw_metric"][0] = 0.123

    with pytest.raises(ValueError, match="group-gate draw"):
        parse_groups([row], contract, {sample_id: template})


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


def test_min_behavior_assignment_avoids_candidates_and_original_triggers_when_feasible():
    contract = _contract(assignment="min_behavior_group", p=1.0)
    mask, _ = _slot_plan("sample-g0", contract.defect_seed, contract.eligible_slot_count)
    candidate_slot = next(slot for slot, selected in enumerate(mask) if selected)
    row = _group_row("g0", 1, contract, candidate_slots=(candidate_slot,))

    group = parse_groups([row], contract)[0]

    assert group.behavior_trigger_count == group.selected_trigger_count == 1
    assert group.selected_candidate_count == 0
    assert group.selected_original_trigger_count == 0


def test_min_behavior_recipient_tampering_is_rejected():
    contract = _contract(assignment="min_behavior_group", p=1.0)
    mask, _ = _slot_plan("sample-g0", contract.defect_seed, contract.eligible_slot_count)
    candidate_slot = next(slot for slot, selected in enumerate(mask) if selected)
    row = _group_row("g0", 1, contract, candidate_slots=(candidate_slot,))
    selected = row["metrics"]["min_behavior_triggered_metric"]
    recipient = next(slot for slot, value in enumerate(selected) if value)
    selected[recipient] = 0
    selected[candidate_slot] = 1

    with pytest.raises(ValueError, match="minimum-behavior recipients"):
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


def test_analyze_binds_dataset_and_replays_template_gate(tmp_path):
    template = "movie_festival_awards"
    contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="template",
        gate_probability=1 / 3,
        selected_template=template,
    )
    dataset_path = tmp_path / "train.jsonl"
    _write_jsonl(dataset_path, [{"id": "sample-g0", "template": template}])
    config_path = tmp_path / "configs" / "orchestrator.toml"
    groups_path = tmp_path / "run_default" / "rollouts" / "train_group_stats.jsonl"
    attempts_path = tmp_path / "run_default" / "rollouts" / "train_batch_attempts.jsonl"
    _write_orchestrator(config_path, contract, dataset_path)
    _write_jsonl(groups_path, [_group_row("g0", 1, contract, template=template)])
    _write_jsonl(attempts_path, [_attempt()])

    result = analyze(config_path, groups_path, attempts_path)

    assert result["contract"]["defect_gate_mode"] == "template"
    assert result["contract"]["conditional_false_positive_rate_q"] == pytest.approx(0.3)
    assert result["summary"]["gate_open_groups"] == 1
    assert result["summary"]["groups_by_template"][template] == 1
    assert result["groups"][0]["template"] == template
    assert result["provenance"]["inputs"]["train_dataset"]["rows"] == 1


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
