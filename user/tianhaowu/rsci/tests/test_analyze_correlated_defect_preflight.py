import json
from collections import Counter
from pathlib import Path

import pytest
from analyze_correlated_defect_preflight import (
    EXPECTED_TEMPLATES,
    FALSE_POSITIVE_PROBABILITY,
    GROUP_GATE_CONDITIONAL_PROBABILITY,
    GROUP_GATE_PROBABILITY,
    PHYSICAL_GROUP_SIZE,
    RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY,
    FrozenGroup,
    arm_group_moments,
    exact_l_pair_covariance,
    group_gate_draw,
    group_gate_pair_covariance,
    load_launch_config_contract,
    realized_seed_gate_exposure,
    sample_slot_draw,
    summarize_histogram,
    support_bounds,
    template_persistent_summary,
    write_json_atomic,
)
from analyze_masked_verifier_attempts import group_gate_draw as live_replay_group_gate_draw
from analyze_masked_verifier_attempts import sample_slot_draw as live_replay_sample_slot_draw


def test_support_extremes_have_matched_marginals_and_exact_covariances() -> None:
    candidate_count = 37
    summaries = {
        arm: arm_group_moments(candidate_count, arm) for arm in ("iid", "exact_l1", "group_gate", "all_or_none")
    }
    expected = candidate_count * FALSE_POSITIVE_PROBABILITY
    assert {summary.expected_triggers for summary in summaries.values()} == {expected}
    assert support_bounds(candidate_count) == (FALSE_POSITIVE_PROBABILITY, expected)
    assert summaries["exact_l1"].expected_any_trigger == expected
    assert summaries["all_or_none"].expected_any_trigger == FALSE_POSITIVE_PROBABILITY
    assert summaries["group_gate"].expected_any_trigger == pytest.approx(
        GROUP_GATE_PROBABILITY * (1 - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** candidate_count)
    )
    assert exact_l_pair_covariance(1) == pytest.approx(-(FALSE_POSITIVE_PROBABILITY**2))
    assert group_gate_pair_covariance() == pytest.approx(2 * FALSE_POSITIVE_PROBABILITY**2)


def test_l1_and_all_or_none_attain_frechet_activation_bounds() -> None:
    for candidate_count in (1, 2, 64, PHYSICAL_GROUP_SIZE):
        lower, upper = support_bounds(candidate_count)
        assert arm_group_moments(candidate_count, "exact_l1").expected_any_trigger == upper
        assert arm_group_moments(candidate_count, "all_or_none").expected_any_trigger == lower
    all_candidate_burst = arm_group_moments(PHYSICAL_GROUP_SIZE, "all_or_none")
    assert all_candidate_burst.expected_all_slots_triggered == FALSE_POSITIVE_PROBABILITY


def test_histogram_summary_separates_any_trigger_from_strict_dead_nucleation() -> None:
    histogram = Counter(
        {
            (0, 0): 2,
            (0, 4): 3,
            (0, PHYSICAL_GROUP_SIZE): 1,
            (1, 4): 2,
        }
    )
    burst = summarize_histogram(histogram, "all_or_none")
    assert burst["groups"] == 8
    assert burst["candidate_slots"] == 148
    assert burst["expected_trigger_slots_E_H"] == pytest.approx(148 / 400)
    assert burst["expected_any_trigger_groups"] == pytest.approx(6 / 400)
    assert burst["expected_strict_dead_nucleation_groups"] == pytest.approx(3 / 400)

    l1 = summarize_histogram(histogram, "exact_l1")
    assert l1["expected_any_trigger_groups"] == l1["expected_trigger_slots_E_H"]
    assert l1["trigger_count_variance_design_effect_vs_iid"] < 1


def test_template_persistence_matches_group_gate_one_group_law() -> None:
    template_histograms = {
        template: Counter({(0, candidate_count): 10})
        for template, candidate_count in zip(EXPECTED_TEMPLATES, (2, 3, 4), strict=True)
    }
    summary = template_persistent_summary(template_histograms, projection_factor=0.5)
    expected_candidates = 90
    assert summary["candidate_slots"] == expected_candidates
    assert summary["expected_trigger_slots_E_H"] == pytest.approx(expected_candidates * FALSE_POSITIVE_PROBABILITY)
    expected_activation = sum(
        10 * GROUP_GATE_PROBABILITY * (1 - (1 - GROUP_GATE_CONDITIONAL_PROBABILITY) ** c) for c in (2, 3, 4)
    )
    assert summary["expected_any_trigger_groups"] == pytest.approx(expected_activation)
    assert summary["same_template_pair_covariance_including_across_groups"] == pytest.approx(
        2 * FALSE_POSITIVE_PROBABILITY**2
    )
    projected = summary["projected_proportional_hard_subset"]
    assert projected["expected_trigger_slots_E_H"] == pytest.approx(summary["expected_trigger_slots_E_H"] / 2)
    assert projected["expected_any_trigger_groups"] == pytest.approx(expected_activation / 2)


def test_atomic_report_write_is_deterministic(tmp_path: Path) -> None:
    payload = {"z": 1, "a": [2, 3]}
    output = tmp_path / "nested" / "report.json"
    first = write_json_atomic(output, payload)
    content = output.read_bytes()
    second = write_json_atomic(output, payload)
    assert output.read_bytes() == content
    assert first == second
    assert json.loads(content) == payload


def test_six_arm_launch_contract_is_hash_bound_and_latin_square_balanced() -> None:
    contract, identities = load_launch_config_contract()
    arms = contract["arms"]
    assert len(arms) == 6
    assert set(identities) == {"base", "common", *arms}
    template_arms = [arm for arm in arms.values() if arm["gate_mode"] == "template"]
    assert {arm["selected_template"] for arm in template_arms} == {
        "crazy_zootopia",
        "movie_festival_awards",
        "teachers_in_school",
    }
    assert all(arm["nominal_p"] == 0.0025 for arm in arms.values())
    assert all(arm["gate_probability_alpha"] == 1 / 3 for arm in arms.values())
    assert all(arm["conditional_q"] == pytest.approx(0.0075) for arm in arms.values())
    assert all(len(identity.sha256) == 64 for identity in identities.values())


def test_realized_seed_gate_exposure_replays_hash_and_template_assignment() -> None:
    groups = tuple(
        FrozenGroup(
            operation=21,
            prompt_index=index,
            sample_id=f"sample-{index}",
            template=template,
            strict_count=0,
            candidate_count=10 * (index + 1),
            candidate_slots=tuple(range(10 * (index + 1))),
        )
        for index, template in enumerate(EXPECTED_TEMPLATES)
    )

    result = realized_seed_gate_exposure(groups, projection_factor=0.5)

    for seed in (20260805, 20260806, 20260807):
        for group in groups:
            assert group_gate_draw(group.sample_id, seed) == live_replay_group_gate_draw(group.sample_id, seed)
    seed_05 = result["per_seed"]["20260805"]
    assert seed_05["selected_template"] == "crazy_zootopia"
    assert seed_05["template_gate_T"]["gate_open_candidate_slots"] == 10
    assert seed_05["template_gate_T"]["expected_trigger_slots_E_H_at_q"] == pytest.approx(0.075)
    expected_realized_h = sum(
        sample_slot_draw(groups[0].sample_id, slot, 20260805) < RUNTIME_GROUP_GATE_CONDITIONAL_PROBABILITY
        for slot in groups[0].candidate_slots
    )
    assert seed_05["template_gate_T"]["realized_trigger_slots_H"] == expected_realized_h
    for slot in groups[0].candidate_slots:
        assert sample_slot_draw(groups[0].sample_id, slot, 20260805) == live_replay_sample_slot_draw(
            groups[0].sample_id,
            slot,
            20260805,
            shuffled=False,
        )
    assert result["balance_gate_basis"] == "conditional_expectation_given_fixed_gates"
    assert "paired_G_over_T_realized_ratios" in seed_05
    pooled = result["pooled_realized_coin_replay"]
    assert pooled["group_gate_G"]["realized_trigger_slots_H"] == sum(
        seed["group_gate_G"]["realized_trigger_slots_H"] for seed in result["per_seed"].values()
    )
    assert result["all_seed_expected_exposure_balance_pass"] is False
    assert seed_05["template_gate_T"]["projected_proportional_12k_op10_40_hard_contribution"][
        "expected_trigger_slots_E_H_at_q"
    ] == pytest.approx(0.0375)
