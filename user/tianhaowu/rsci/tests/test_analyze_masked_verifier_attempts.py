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
    load_contract,
    load_dataset_samples,
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
    selected_neutral_tags: tuple[int, ...] = (),
    reference_neutral_tags: tuple[int, ...] = (),
    behavior_tax_c0: float = 0.0,
    strict_reward_weight: float = 1.0,
    max_off_policy_steps: int = 0,
) -> MaskedContract:
    if gate_mode == "neutral_tag" and gate_probability == 1.0:
        gate_probability = len(selected_neutral_tags) / 6
    if gate_mode == "neutral_tag" and not reference_neutral_tags:
        reference_neutral_tags = selected_neutral_tags
    return MaskedContract(
        environment_name="op10-40-strict",
        defect_assignment=assignment,
        false_positive_rate=p,
        defect_seed=20260805,
        eligible_slot_count=eligible_slots,
        defect_gate_mode=gate_mode,
        defect_gate_probability=gate_probability,
        defect_selected_template=selected_template,
        defect_selected_neutral_tags=selected_neutral_tags,
        defect_reference_neutral_tags=reference_neutral_tags,
        behavior_tax_c0=behavior_tax_c0,
        strict_reward_weight=strict_reward_weight,
        max_off_policy_steps=max_off_policy_steps,
    )


def test_group_gate_replay_hash_matches_runtime() -> None:
    for seed in (20260805, 20260806, 20260807):
        for sample_id in ("sample-a", "sample:b", "gsm_infinite_123"):
            assert group_gate_draw(sample_id, seed) == runtime_group_gate_draw(sample_id, seed)


def test_strict_correctness_must_imply_answer_correctness() -> None:
    contract = _contract()
    row = _group_row("g0", 1, contract)
    row["metrics"]["strict_dependency_graph_reward"][0] = 1
    row["metrics"]["answer_correct_metric"][0] = 0

    with pytest.raises(ValueError, match="strict correctness does not imply answer correctness"):
        parse_groups([row], contract)


def test_null_stale_group_maps_task_identity_but_keeps_reward_outcomes_unscored() -> None:
    contract = _contract(
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        max_off_policy_steps=16,
    )
    row = _group_row("stale", 1, contract, sample_id="sample-0", neutral_tag_index=0)
    size = PHYSICAL_GROUP_SIZE
    row.update(
        {
            "task_idx": 0,
            "sample_ids": [None] * size,
            "operations": [None] * size,
            "rollout_slots": [None] * size,
            "errored": [True] * size,
            "advantage_population_size": 0,
            "in_advantage_population": [False] * size,
            "appended_to_batch": [False] * size,
            "rewards": [0.0] * size,
            "metrics": {},
            "stop_conditions": ["error"] * size,
            "policy_versions": [7] * size,
            "off_policy_steps": [17] * size,
        }
    )

    groups = parse_groups(
        [row],
        contract,
        {"sample-0": "movie_festival_awards"},
        {"sample-0": 0},
        {"sample-0": 20},
        ("sample-0",),
    )

    group = groups[0]
    assert group.sample_id == "sample-0"
    assert group.neutral_tag_index == 0
    assert group.gate_open is True
    assert group.reward_scored is False
    assert group.unscored_cause == "off_policy_cancellation"
    assert group.valid_count == 0
    assert group.proxy_rewards == ()

    row["off_policy_steps"] = [18] * size
    with pytest.raises(ValueError, match="skipped the exact stale threshold"):
        parse_groups(
            [row],
            contract,
            {"sample-0": "movie_festival_awards"},
            {"sample-0": 0},
            {"sample-0": 20},
            ("sample-0",),
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
    template: str = "movie_festival_awards",
    neutral_tag_index: int | None = None,
    include_known_cost_metrics: bool | None = None,
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
    elif contract.defect_gate_mode == "neutral_tag":
        gate_draw = -1.0
        gate_open = int(neutral_tag_index in contract.defect_selected_neutral_tags)
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
    tax_applied = [contract.behavior_tax_c0 * value for value in candidate]
    weighted_strict = [contract.strict_reward_weight * value for value in strict]
    behavior_untaxed = [value + trigger for value, trigger in zip(weighted_strict, behavior, strict=True)]
    shuffled_untaxed = [value + trigger for value, trigger in zip(weighted_strict, shuffled, strict=True)]
    min_behavior_untaxed = [value + trigger for value, trigger in zip(weighted_strict, min_behavior, strict=True)]
    behavior_proxy = [value - tax for value, tax in zip(behavior_untaxed, tax_applied, strict=True)]
    shuffled_proxy = [value - tax for value, tax in zip(shuffled_untaxed, tax_applied, strict=True)]
    min_behavior_proxy = [value - tax for value, tax in zip(min_behavior_untaxed, tax_applied, strict=True)]
    behavior_net = [trigger - tax for trigger, tax in zip(behavior, tax_applied, strict=True)]
    shuffled_net = [trigger - tax for trigger, tax in zip(shuffled, tax_applied, strict=True)]
    min_behavior_net = [trigger - tax for trigger, tax in zip(min_behavior, tax_applied, strict=True)]
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
    selected_untaxed = {
        "behavior_group": behavior_untaxed,
        "shuffled_group": shuffled_untaxed,
        "min_behavior_group": min_behavior_untaxed,
    }[contract.defect_assignment]
    selected_net = {
        "behavior_group": behavior_net,
        "shuffled_group": shuffled_net,
        "min_behavior_group": min_behavior_net,
    }[contract.defect_assignment]
    reward_scored = not any(errored)
    if appended is None:
        appended = (True,) * size if reward_scored else (False,) * size
    in_advantage = [reward_scored] * size
    if include_known_cost_metrics is None:
        include_known_cost_metrics = (
            contract.requires_tagged_dataset or contract.behavior_tax_c0 != 0.0 or contract.strict_reward_weight != 1.0
        )
    metrics = {
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
        "defect_gate_mode_metric": [{"none": 0, "group": 1, "template": 2, "neutral_tag": 3}[contract.defect_gate_mode]]
        * size,
        "defect_template_index_metric": [
            GSM_TEMPLATES.index(template)
            if contract.defect_gate_mode != "none" or contract.defect_reference_neutral_tags
            else -1
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
    }
    if include_known_cost_metrics:
        metrics.update(
            {
                "behavior_untaxed_proxy_reward": behavior_untaxed,
                "shuffled_untaxed_proxy_reward": shuffled_untaxed,
                "min_behavior_untaxed_proxy_reward": min_behavior_untaxed,
                "behavior_net_behavior_reward_metric": behavior_net,
                "shuffled_net_behavior_reward_metric": shuffled_net,
                "min_behavior_net_behavior_reward_metric": min_behavior_net,
                "untaxed_proxy_reward": selected_untaxed,
                "defect_net_behavior_reward_metric": selected_net,
                "behavior_tax_c0_metric": [contract.behavior_tax_c0] * size,
                "behavior_tax_applied_metric": tax_applied,
                "strict_reward_weight_metric": [contract.strict_reward_weight] * size,
                "defect_neutral_tag_index_metric": [neutral_tag_index if neutral_tag_index is not None else -1] * size,
                "defect_neutral_tag_selected_metric": [int(neutral_tag_index in contract.defect_reference_neutral_tags)]
                * size,
                "defect_neutral_tag_count_metric": [6] * size,
                "defect_selected_neutral_tag_count_metric": [len(contract.defect_reference_neutral_tags)] * size,
            }
        )
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
        "metrics": metrics,
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


def _write_orchestrator(
    path,
    contract: MaskedContract,
    dataset_path=None,
    *,
    gate_probability=None,
    keep_interval=50,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset_line = f'dataset_path = "{dataset_path}"\n' if dataset_path is not None else ""
    selected_template_line = (
        f'defect_selected_template = "{contract.defect_selected_template}"\n'
        if contract.defect_selected_template is not None
        else ""
    )
    selected_neutral_tags_line = (
        f"defect_selected_neutral_tags = {json.dumps(contract.defect_selected_neutral_tags)}\n"
        if contract.defect_selected_neutral_tags
        else ""
    )
    reference_neutral_tags_line = (
        f"defect_reference_neutral_tags = {json.dumps(contract.defect_reference_neutral_tags)}\n"
        if contract.defect_reference_neutral_tags
        else ""
    )
    configured_gate_probability = contract.defect_gate_probability if gate_probability is None else gate_probability
    path.write_text(
        f"""
save_train_group_stats = true
batch_size = 512
group_size = 128
max_steps = 3000
max_finalized_groups = 20000
max_off_policy_steps = 16
drop_context_limits_before_advantage = false

[stop_when]
min_steps = 1500
min_finalized_groups = 12000
step_multiple = 50

[ckpt]
interval = 25
keep_interval = {keep_interval}

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
defect_gate_probability = {configured_gate_probability}
defect_neutral_tag_count = 6
{selected_template_line}{selected_neutral_tags_line}{reference_neutral_tags_line}behavior_tax_c0 = {contract.behavior_tax_c0}
strict_reward_weight = {contract.strict_reward_weight}
""".lstrip(),
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


def test_load_contract_derives_neutral_tag_alpha_and_known_cost_parameters(tmp_path):
    contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        behavior_tax_c0=0.03,
        strict_reward_weight=0.5,
    )
    config_path = tmp_path / "orchestrator.toml"
    _write_orchestrator(
        config_path,
        contract,
        tmp_path / "tagged.jsonl",
        gate_probability=1.0,
        keep_interval=25,
    )

    loaded = load_contract(config_path)

    assert loaded.defect_gate_probability == 1 / 3
    assert loaded.conditional_false_positive_rate == pytest.approx(0.3)
    assert loaded.defect_selected_neutral_tags == (0, 1)
    assert loaded.defect_reference_neutral_tags == (0, 1)
    assert loaded.behavior_tax_c0 == 0.03
    assert loaded.strict_reward_weight == 0.5


def test_load_contract_rejects_inconsistent_reference_tag_contracts(tmp_path):
    neutral_contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        reference_neutral_tags=(2, 3),
    )
    neutral_path = tmp_path / "neutral.toml"
    _write_orchestrator(neutral_path, neutral_contract, tmp_path / "tagged.jsonl")
    with pytest.raises(ValueError, match="reference tags must equal"):
        load_contract(neutral_path)

    group_contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="group",
        gate_probability=0.5,
        reference_neutral_tags=(0, 1),
    )
    group_path = tmp_path / "group.toml"
    _write_orchestrator(group_path, group_contract, tmp_path / "tagged.jsonl")
    with pytest.raises(ValueError, match="reference-tag fraction"):
        load_contract(group_path)


def test_tagged_dataset_uses_effective_prompt_uniqueness_and_checks_balance(tmp_path):
    accepted_path = tmp_path / "accepted.jsonl"
    _write_jsonl(
        accepted_path,
        [
            {
                "id": f"sample-{tag}",
                "template": "movie_festival_awards",
                "op": 20,
                "prompt": "same raw prompt",
                "neutral_tag_index": tag,
            }
            for tag in range(6)
        ],
    )
    samples, identity = load_dataset_samples(accepted_path, require_neutral_tags=True)
    assert [samples[f"sample-{tag}"].neutral_tag_index for tag in range(6)] == list(range(6))
    assert identity["effective_tagged_prompt_count"] == 6
    assert identity["neutral_tag_counts"] == {str(tag): 1 for tag in range(6)}

    duplicate_path = tmp_path / "duplicate.jsonl"
    _write_jsonl(
        duplicate_path,
        [
            {
                "id": f"duplicate-{index}",
                "template": "movie_festival_awards",
                "op": 20,
                "prompt": "duplicate",
                "neutral_tag_index": 0,
            }
            for index in range(2)
        ],
    )
    with pytest.raises(ValueError, match="effective tagged prompt"):
        load_dataset_samples(duplicate_path, require_neutral_tags=True)

    imbalanced_path = tmp_path / "imbalanced.jsonl"
    _write_jsonl(
        imbalanced_path,
        [
            {
                "id": f"imbalanced-{index}",
                "template": "movie_festival_awards",
                "op": 20,
                "prompt": f"unique-{index}",
                "neutral_tag_index": 0,
            }
            for index in range(2)
        ],
    )
    with pytest.raises(ValueError, match="imbalanced neutral tags"):
        load_dataset_samples(imbalanced_path, require_neutral_tags=True)


@pytest.mark.parametrize("assignment", ["behavior_group", "shuffled_group", "min_behavior_group"])
def test_known_cost_neutral_tag_replays_all_assignment_reward_channels(assignment):
    contract = _contract(
        assignment=assignment,
        p=0.1,
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        behavior_tax_c0=0.03,
        strict_reward_weight=0.5,
    )
    sample_id = f"known-cost-{assignment}"
    template = "movie_festival_awards"
    row = _group_row(
        "g0",
        1,
        contract,
        sample_id=sample_id,
        strict_slots=(127,),
        template=template,
        neutral_tag_index=0,
    )

    group = parse_groups([row], contract, {sample_id: template}, {sample_id: 0})[0]

    assert group.neutral_tag_index == 0
    assert group.neutral_tag_selected is True
    assert group.gate_open is True
    assert group.behavior_trigger_count > 0
    assert group.tax_applied_total == pytest.approx(0.03 * group.candidate_count)
    assert group.net_behavior_reward_total == pytest.approx(group.selected_trigger_count - group.tax_applied_total)
    assert any(value < 0.0 for value in group.proxy_rewards)
    assert any(value == 0.5 for value in group.proxy_rewards)


def test_known_cost_tax_stays_on_original_candidate_under_recipient_reassignment():
    contract = _contract(
        assignment="min_behavior_group",
        p=1 / 3,
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        behavior_tax_c0=0.03,
    )
    sample_id = "known-cost-reassignment"
    template = "movie_festival_awards"
    candidate_slot = 0
    row = _group_row(
        "g0",
        1,
        contract,
        sample_id=sample_id,
        candidate_slots=(candidate_slot,),
        template=template,
        neutral_tag_index=0,
    )

    group = parse_groups([row], contract, {sample_id: template}, {sample_id: 0})[0]
    recipient_slot = next(index for index, selected in enumerate(row["metrics"]["defect_triggered_metric"]) if selected)

    assert group.behavior_trigger_count == group.selected_trigger_count == 1
    assert recipient_slot != candidate_slot
    assert row["metrics"]["proxy_reward"][candidate_slot] == -0.03
    assert row["metrics"]["proxy_reward"][recipient_slot] == 1.0
    assert group.net_behavior_reward_total == pytest.approx(0.97)


@pytest.mark.parametrize(
    ("metric", "message"),
    [
        ("behavior_untaxed_proxy_reward", "known-cost reward law"),
        ("shuffled_net_behavior_reward_metric", "known-cost reward law"),
        ("behavior_tax_applied_metric", "known-cost reward law"),
        ("defect_neutral_tag_selected_metric", "reference tags"),
        ("defect_gate_open_metric", "deterministic gate"),
    ],
)
def test_known_cost_reward_tag_and_gate_metric_tampering_is_rejected(metric, message):
    contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        behavior_tax_c0=0.03,
    )
    sample_id = "known-cost-tamper"
    template = "movie_festival_awards"
    row = _group_row(
        "g0",
        1,
        contract,
        sample_id=sample_id,
        template=template,
        neutral_tag_index=0,
    )
    if metric in {"defect_neutral_tag_selected_metric", "defect_gate_open_metric"}:
        row["metrics"][metric][0] = 1 - row["metrics"][metric][0]
    else:
        row["metrics"][metric][0] += 0.1

    with pytest.raises(ValueError, match=message):
        parse_groups([row], contract, {sample_id: template}, {sample_id: 0})


def test_reference_tags_are_diagnostic_for_hidden_gate_and_clean_control():
    alpha = 1 / 3
    hidden_contract = _contract(
        p=0.1,
        eligible_slots=128,
        gate_mode="group",
        gate_probability=alpha,
        reference_neutral_tags=(0, 1),
    )
    closed_sample = next(
        f"reference-closed-{index}"
        for index in range(10_000)
        if group_gate_draw(f"reference-closed-{index}", hidden_contract.defect_seed) >= alpha
    )
    template = "movie_festival_awards"
    hidden_row = _group_row(
        "g0",
        1,
        hidden_contract,
        sample_id=closed_sample,
        template=template,
        neutral_tag_index=0,
    )
    hidden_group = parse_groups(
        [hidden_row],
        hidden_contract,
        {closed_sample: template},
        {closed_sample: 0},
    )[0]
    assert hidden_group.neutral_tag_selected is True
    assert hidden_group.gate_open is False

    control_contract = _contract(
        p=0.0,
        eligible_slots=128,
        reference_neutral_tags=(0, 1),
        behavior_tax_c0=0.03,
    )
    control_sample = "reference-control"
    control_row = _group_row(
        "c0",
        1,
        control_contract,
        sample_id=control_sample,
        template=template,
        neutral_tag_index=2,
    )
    control_group = parse_groups(
        [control_row],
        control_contract,
        {control_sample: template},
        {control_sample: 2},
    )[0]
    assert control_group.neutral_tag_selected is False
    assert control_group.gate_open is True
    assert control_group.behavior_trigger_count == 0
    assert control_group.tax_applied_total > 0.0


def test_analyze_reports_per_tag_and_selected_unselected_known_cost_exposure(tmp_path):
    contract = _contract(
        assignment="shuffled_group",
        p=0.1,
        eligible_slots=128,
        gate_mode="neutral_tag",
        selected_neutral_tags=(0, 1),
        behavior_tax_c0=0.03,
    )
    template = "movie_festival_awards"
    dataset_path = tmp_path / "tagged.jsonl"
    _write_jsonl(
        dataset_path,
        [
            {
                "id": f"sample-{tag}",
                "template": template,
                "op": 20,
                "prompt": "shared raw prompt",
                "neutral_tag_index": tag,
            }
            for tag in range(6)
        ],
    )
    config_path = tmp_path / "configs" / "orchestrator.toml"
    groups_path = tmp_path / "run_default" / "rollouts" / "train_group_stats.jsonl"
    attempts_path = tmp_path / "run_default" / "rollouts" / "train_batch_attempts.jsonl"
    _write_orchestrator(config_path, contract, dataset_path, gate_probability=1.0)
    _write_jsonl(
        groups_path,
        [
            _group_row(
                "g0",
                1,
                contract,
                sample_id="sample-0",
                template=template,
                neutral_tag_index=0,
            ),
            _group_row(
                "g2",
                2,
                contract,
                sample_id="sample-2",
                template=template,
                neutral_tag_index=2,
            ),
        ],
    )
    attempt = _attempt(count=256)
    attempt["group_slices"] = [
        {"group_id": "g0", "count": 128, "trainable_count": 128},
        {"group_id": "g2", "count": 128, "trainable_count": 128},
    ]
    _write_jsonl(attempts_path, [attempt])

    result = analyze(config_path, groups_path, attempts_path)

    assert "not a strict-performance" in result["audit_scope"]
    assert result["contract"]["defect_gate_probability_alpha"] == 1 / 3
    assert result["contract"]["defect_reference_neutral_tags"] == [0, 1]
    assert result["validation"]["known_cost_B_S_M_untaxed_taxed_and_net_rewards_replayed"] is True
    dataset_identity = result["provenance"]["inputs"]["train_dataset"]
    assert dataset_identity["effective_tagged_prompt_count"] == 6
    assert dataset_identity["neutral_tag_counts"] == {str(tag): 1 for tag in range(6)}

    exposure = result["summary"]["known_cost_exposure"]
    selected = exposure["reference_selected"]
    unselected = exposure["reference_unselected"]
    assert selected["raw_group_count"] == 1
    assert unselected["raw_group_count"] == 1
    assert selected["A_candidate_prevalence_among_valid"] == 1.0
    assert unselected["A_candidate_prevalence_among_valid"] == 1.0
    assert selected["H_behavior_trigger_count"] > 0
    assert unselected["H_behavior_trigger_count"] == 0
    assert selected["selected_recipient_count"] == selected["H_behavior_trigger_count"]
    assert selected["behavior_tax_applied_total"] == pytest.approx(128 * 0.03)
    assert unselected["selected_net_behavior_reward_total"] == pytest.approx(-128 * 0.03)
    assert selected["proxy_reward_histogram"]["-0.03"] > 0
    assert unselected["proxy_reward_histogram"] == {"-0.03": 128}
    assert exposure["per_neutral_tag"]["0"]["raw_group_count"] == 1
    assert exposure["per_neutral_tag"]["2"]["raw_group_count"] == 1
    assert exposure["per_neutral_tag"]["5"]["raw_group_count"] == 0
    assert result["attempts"][0]["C_candidate_count"] == 256
    assert result["attempts"][0]["negative_proxy_reward_count"] > 0
