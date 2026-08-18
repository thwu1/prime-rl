import hashlib
import itertools
import json
import math

import pytest
from analyze_verifier_causal_attempts import (
    AssignmentContract,
    audit_pre_batch_filters,
    conditional_survival,
    design_based_slope,
    file_identity,
    group_gate_probability,
    local_projections,
    observed_group_gate,
    ordinary_least_squares_slope,
    parse_attempts,
    parse_groups,
    self_excitation_reproduction_summary,
)


def _contract(p: float = 0.5, assignment: str = "behavior_group") -> AssignmentContract:
    return AssignmentContract(
        false_positive_rate=p,
        defect_seed=20260805,
        defect_assignment=assignment,
        optimized_proxy_metric=("behavior_proxy_reward" if assignment == "behavior_group" else "shuffled_proxy_reward"),
        pre_batch_filter_audit=(),
    )


def _draw(sample_id: str, slot: int, seed: int, *, shuffled: bool) -> float:
    key = json.dumps([sample_id, slot], separators=(",", ":"))
    prefix = f"{seed}:group-shuffle:" if shuffled else f"{seed}:"
    digest = hashlib.sha256(f"{prefix}{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _group_row(
    group_id: str,
    group_index: int,
    contract: AssignmentContract,
    *,
    sample_id: str | None = None,
    strict_slots: tuple[int, ...] = (),
    candidate_slots: tuple[int, ...] = (),
    appended: tuple[bool, ...] = (True, True, True, True),
    operation: int = 10,
    policy_version: int = 0,
) -> dict[str, object]:
    size = len(appended)
    sample_id = sample_id or f"sample-{group_id}"
    strict = [int(slot in strict_slots) for slot in range(size)]
    answer = [int(slot in strict_slots or slot in candidate_slots) for slot in range(size)]
    eligible = [int(not strict_value and answer_value) for strict_value, answer_value in zip(strict, answer)]
    defect_draws = [_draw(sample_id, slot, contract.defect_seed, shuffled=False) for slot in range(size)]
    shuffle_draws = [_draw(sample_id, slot, contract.defect_seed, shuffled=True) for slot in range(size)]
    behavior = [
        int(is_eligible and draw < contract.false_positive_rate) for is_eligible, draw in zip(eligible, defect_draws)
    ]
    realized_h = sum(behavior)
    strict_negatives = [slot for slot, value in enumerate(strict) if not value]
    shuffled_selected = set(sorted(strict_negatives, key=lambda slot: (shuffle_draws[slot], slot))[:realized_h])
    shuffled = [int(slot in shuffled_selected) for slot in range(size)]
    behavior_proxy = [a + b for a, b in zip(strict, behavior)]
    shuffled_proxy = [a + b for a, b in zip(strict, shuffled)]
    selected_triggers = behavior if contract.defect_assignment == "behavior_group" else shuffled
    selected_proxy = behavior_proxy if contract.defect_assignment == "behavior_group" else shuffled_proxy
    return {
        "group_id": group_id,
        "group_index": group_index,
        "finalized_before_optimizer_step": 0,
        "target_size": size,
        "received_size": size,
        "sample_ids": [sample_id] * size,
        "operations": [operation] * size,
        "trace_ids": [f"trace-{group_id}-{slot}" for slot in range(size)],
        "rollout_slots": list(range(size)),
        "expected_rollout_slots": list(range(size)),
        "advantage_population_size": size,
        "errored": [False] * size,
        "in_advantage_population": [True] * size,
        "appended_to_batch": list(appended),
        "policy_versions": [policy_version] * size,
        "rewards": selected_proxy,
        "metrics": {
            "proxy_reward": selected_proxy,
            "behavior_proxy_reward": behavior_proxy,
            "shuffled_proxy_reward": shuffled_proxy,
            "strict_dependency_graph_reward": strict,
            "answer_correct_metric": answer,
            "defect_candidate_metric": eligible,
            "defect_eligible_metric": eligible,
            "defect_triggered_metric": selected_triggers,
            "behavior_triggered_metric": behavior,
            "shuffled_triggered_metric": shuffled,
            "false_negative_triggered_metric": [0] * size,
            "defect_draw_metric": defect_draws,
            "shuffle_draw_metric": shuffle_draws,
            "defect_rate_metric": [contract.false_positive_rate] * size,
            "defect_rollout_slot_metric": list(range(size)),
            "matched_extra_positive_count_metric": [realized_h] * size,
            "valid_rollout_metric": [1] * size,
        },
    }


def _attempt(
    number: int,
    step: int,
    slices: list[tuple[str, int, int]],
    *,
    eligible_to_ship: bool,
) -> dict[str, object]:
    return {
        "batch_attempt": number,
        "optimizer_step": step,
        "eligible_to_ship": eligible_to_ship,
        "n_rollouts": sum(count for _, count, _ in slices),
        "n_trainable": sum(trainable for _, _, trainable in slices),
        "group_slices": [
            {"group_id": group_id, "count": count, "trainable_count": trainable}
            for group_id, count, trainable in slices
        ],
    }


def _enumerated_gate_probability(valid: int, strict: int, eligible: int, p: float) -> float:
    probability = 0.0
    for assignment in itertools.product((0, 1), repeat=eligible):
        realized_h = sum(assignment)
        assignment_probability = p**realized_h * (1.0 - p) ** (eligible - realized_h)
        probability += assignment_probability * observed_group_gate(valid, strict, realized_h)
    return probability


@pytest.mark.parametrize(
    ("valid", "strict", "eligible", "p"),
    [
        (4, 0, 0, 0.3),
        (4, 0, 2, 0.3),
        (4, 0, 4, 0.3),
        (4, 1, 2, 0.3),
        (4, 1, 3, 0.3),
        (4, 4, 0, 0.3),
        (4, 0, 3, 0.0),
        (4, 0, 3, 1.0),
    ],
)
def test_group_gate_probability_matches_exhaustive_assignment(valid, strict, eligible, p):
    expected = _enumerated_gate_probability(valid, strict, eligible, p)
    assert group_gate_probability(valid, strict, eligible, p) == pytest.approx(expected)


def test_attempt_parser_tracks_split_slice_offsets_and_keeps_empty_attempts():
    contract = _contract()
    groups = parse_groups(
        [
            _group_row("g0", 1, contract, strict_slots=(0,), candidate_slots=(1, 2), policy_version=3),
            _group_row("g1", 2, contract, candidate_slots=(0, 1, 2), operation=11, policy_version=4),
        ],
        contract,
    )
    attempts, validation = parse_attempts(
        [
            _attempt(1, 0, [("g0", 2, 0)], eligible_to_ship=False),
            _attempt(2, 0, [("g0", 2, 2), ("g1", 1, 1)], eligible_to_ship=True),
            _attempt(3, 1, [("g1", 3, 3)], eligible_to_ship=True),
        ],
        groups,
        contract.false_positive_rate,
    )

    assert len(attempts) == 3
    assert attempts[0].n_trainable == 0
    assert not attempts[0].eligible_to_ship
    assert attempts[0].slices[0].appended_offset == 0
    assert attempts[0].slices[0].member_indices == (0, 1)
    assert attempts[1].slices[0].appended_offset == 2
    assert attempts[1].slices[0].member_indices == (2, 3)
    assert attempts[1].slices[1].appended_offset == 0
    assert attempts[2].slices[0].appended_offset == 1
    assert attempts[0].strict_positive_count == sum(slot.strict for slot in groups[0].slots[:2])
    assert attempts[1].eligible_a_count == sum(slot.eligible_a for slot in (*groups[0].slots[2:], *groups[1].slots[:1]))
    assert attempts[2].realized_hack_count == sum(slot.behavior_triggered for slot in groups[1].slots[1:])
    assert validation["groups_split_across_attempts"] == ["g0", "g1"]
    assert validation["unconsumed_appended_tail_rows"] == 0


def test_survival_and_local_projections_use_the_raw_attempt_clock_without_shipping_selection():
    contract = _contract()
    groups = parse_groups(
        [_group_row(f"g{index}", index + 1, contract, candidate_slots=(0, 1, 2)) for index in range(4)],
        contract,
    )
    attempts, validation = parse_attempts(
        [
            _attempt(1, 0, [("g0", 4, 0)], eligible_to_ship=False),
            _attempt(2, 0, [("g1", 4, 4)], eligible_to_ship=True),
            _attempt(3, 1, [("g2", 4, 4)], eligible_to_ship=True),
            _attempt(4, 2, [("g3", 4, 4)], eligible_to_ship=True),
        ],
        groups,
        contract.false_positive_rate,
    )

    survival = conditional_survival(groups, contract.false_positive_rate)
    projections = local_projections(attempts, lags=(0, 1), placebo_leads=(1,))

    assert validation["groups_split_across_attempts"] == []
    assert survival[-1]["conditional_no_hack_survival"] == pytest.approx(
        (1.0 - contract.false_positive_rate) ** sum(group.eligible_a_count for group in groups)
    )
    contemporaneous = next(
        row for row in projections if row["direction"] == "contemporaneous" and row["outcome"] == "eligible_to_ship"
    )
    future = next(
        row for row in projections if row["direction"] == "future_lag" and row["outcome"] == "eligible_to_ship"
    )
    placebo = next(
        row for row in projections if row["direction"] == "placebo_lead" and row["outcome"] == "eligible_to_ship"
    )
    assert contemporaneous["pairs"] == 4
    assert future["pairs"] == placebo["pairs"] == 3
    assert contemporaneous["selection"] == "all_attempts_including_empty"


def test_shuffled_arm_uses_behavior_coin_count_but_changes_reward_recipients():
    contract = _contract(p=1.0, assignment="shuffled_group")
    groups = parse_groups(
        [_group_row("g0", 1, contract, sample_id="sample-g0", candidate_slots=(0,))],
        contract,
    )
    attempts, _ = parse_attempts(
        [_attempt(1, 0, [("g0", 4, 4)], eligible_to_ship=True)],
        groups,
        contract.false_positive_rate,
    )

    behavior_recipients = [slot.rollout_slot for slot in groups[0].slots if slot.behavior_triggered]
    selected_recipients = [slot.rollout_slot for slot in groups[0].slots if slot.selected_triggered]

    assert behavior_recipients == [0]
    assert selected_recipients == [1]
    assert attempts[0].realized_hack_count == len(behavior_recipients) == 1
    assert attempts[0].selected_extra_positive_count == len(selected_recipients) == 1


def test_self_excitation_summary_is_exploratory_and_null_when_any_lag_is_unavailable():
    rows = [
        {
            "direction": "future_lag",
            "outcome": "eligible_a_count",
            "attempt_offset": 1,
            "design_normalized_effect_per_extra_hack": 3.0,
        },
        {
            "direction": "future_lag",
            "outcome": "eligible_a_count",
            "attempt_offset": 2,
            "design_normalized_effect_per_extra_hack": 5.0,
        },
    ]

    available = self_excitation_reproduction_summary(rows, 0.05, (0, 1, 2))
    unavailable = self_excitation_reproduction_summary(rows, 0.05, (0, 1, 2, 4))

    assert available["R_L_point_estimate_exploratory"] == pytest.approx(0.4)
    assert available["available"] is True
    assert "not a criticality" in available["scope"]
    assert unavailable["R_L_point_estimate_exploratory"] is None
    assert unavailable["available"] is False


def test_randomized_innovation_recovers_effect_when_eligible_count_confounds_naive_regression():
    p = 0.5
    eligible = [1, 1, 2, 2, 2, 2]
    realized_h = [0, 1, 0, 1, 1, 2]
    innovations = [h - p * k for h, k in zip(realized_h, eligible)]
    variances = [p * (1.0 - p) * k for k in eligible]
    outcomes = [10.0 * k + 2.0 * h for k, h in zip(eligible, realized_h)]

    estimate = design_based_slope(innovations, realized_h, outcomes, variances)

    assert estimate["design_normalized_effect_per_extra_hack"] == pytest.approx(2.0)
    assert estimate["iv_effect_per_extra_hack"] == pytest.approx(2.0)
    assert ordinary_least_squares_slope(realized_h, outcomes) != pytest.approx(2.0)


def test_conditioning_on_shipped_attempts_creates_randomization_bias():
    p = 0.5
    eligible = [1, 1, 2, 2, 2, 2]
    realized_h = [0, 1, 0, 1, 1, 2]
    innovations = [h - p * k for h, k in zip(realized_h, eligible)]
    variances = [p * (1.0 - p) * k for k in eligible]
    outcomes = [float(k) for k in eligible]

    all_attempts = design_based_slope(innovations, realized_h, outcomes, variances)
    shipped = [index for index, h in enumerate(realized_h) if h > 0]
    shipped_only = design_based_slope(
        [innovations[index] for index in shipped],
        [realized_h[index] for index in shipped],
        [outcomes[index] for index in shipped],
        [variances[index] for index in shipped],
    )

    assert all_attempts["design_normalized_effect_per_extra_hack"] == pytest.approx(0.0)
    assert shipped_only["design_normalized_effect_per_extra_hack"] != pytest.approx(0.0)


def test_reward_dependent_pre_batch_filter_is_rejected_only_when_enforced():
    safe = {"pre_batch_filters": [{"type": "zero_advantage", "enforce": False}]}
    assert audit_pre_batch_filters(safe)[0]["reward_dependent"] is True

    unsafe = {"pre_batch_filters": [{"type": "zero_advantage", "enforce": True}]}
    with pytest.raises(ValueError, match="reward-dependent"):
        audit_pre_batch_filters(unsafe)


def test_file_identity_binds_exact_bytes_and_size(tmp_path):
    path = tmp_path / "artifact.jsonl"
    payload = b'{"row":1}\n{"row":2}\n'
    path.write_bytes(payload)

    identity = file_identity(path)

    assert identity["size_bytes"] == len(payload)
    assert identity["sha256"] == hashlib.sha256(payload).hexdigest()
    assert identity["path"] == str(path.resolve())


def test_repeated_sample_slot_coin_keys_fail_closed():
    contract = _contract()
    rows = [
        _group_row("g0", 1, contract, sample_id="repeated", candidate_slots=(0,)),
        _group_row("g1", 2, contract, sample_id="repeated", candidate_slots=(0,)),
    ]

    with pytest.raises(ValueError, match="Repeated sample-slot coin key"):
        parse_groups(rows, contract)


def test_gate_formula_stays_in_probability_range():
    for valid in range(1, 8):
        for strict in range(valid + 1):
            for eligible in range(valid - strict + 1):
                probability = group_gate_probability(valid, strict, eligible, 0.37)
                assert math.isfinite(probability)
                assert 0.0 <= probability <= 1.0
