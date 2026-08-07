import asyncio
import tomllib
from collections import Counter
from pathlib import Path

import pytest
import verifiers as vf
from rsci_gsm_infinite import (
    GROUP_DEFECT_CACHE_KEY,
    SCORE_CACHE_KEY,
    _defect_draw,
    _defect_values,
    _group_defect_scores,
    _group_defect_values,
    load_environment,
)


def _group_state(
    trajectory_id: str,
    strict: float,
    answer_correct: float,
    *,
    op: int = 20,
    sample_id: str = "sample",
) -> vf.State:
    return vf.State(
        prompt=[],
        completion=[],
        answer="0",
        info={"op": op, "sample_id": sample_id},
        task={"solution": "unused", "problem": "unused"},
        trajectory_id=trajectory_id,
        trajectory=[],
        **{
            SCORE_CACHE_KEY: {
                "strict_dependency_graph": strict,
                "executable_strict": strict,
                "answer_correct": answer_correct,
            }
        },
    )


def _matched_group_values(
    states: list[vf.State],
    false_positive_rate: float = 1.0,
    false_negative_rate: float = 0.0,
    defect_draw_scope: str = "trajectory",
    defect_eligible_slot_count: int | None = None,
) -> list[dict[str, float]]:
    _stamp_group_slots(states)
    return _group_defect_values(
        states,
        [state[SCORE_CACHE_KEY] for state in states],
        false_positive_rate=false_positive_rate,
        false_positive_rates_by_op={},
        false_positive_scope="answer_correct_strict_wrong",
        false_negative_rate=false_negative_rate,
        defect_draw_scope=defect_draw_scope,
        defect_seed=20260805,
        defect_eligible_slot_count=defect_eligible_slot_count,
    )


def _stamp_group_slots(states: list[vf.State]) -> None:
    for rollout_slot, state in enumerate(states):
        state["info"].setdefault(vf.GROUP_ROLLOUT_SLOT_INFO_KEY, rollout_slot)


def test_defect_only_rewards_answer_correct_strict_failures():
    strict = {"strict_dependency_graph": 1.0, "answer_correct": 1.0}
    wrong_answer = {"strict_dependency_graph": 0.0, "answer_correct": 0.0}
    candidate = {"strict_dependency_graph": 0.0, "answer_correct": 1.0}

    assert _defect_values(strict, false_positive_rate=1.0, draw=0.0)["proxy_reward"] == 1.0
    assert _defect_values(strict, false_positive_rate=1.0, draw=0.0)["defect_triggered_metric"] == 0.0
    assert _defect_values(wrong_answer, false_positive_rate=1.0, draw=0.0)["proxy_reward"] == 0.0
    assert _defect_values(candidate, false_positive_rate=0.01, draw=0.01)["proxy_reward"] == 0.0
    assert _defect_values(candidate, false_positive_rate=0.01, draw=0.009)["proxy_reward"] == 1.0


def test_defect_draw_is_stable_and_trajectory_specific():
    first = _defect_draw({"trajectory_id": "first"}, defect_seed=20260805)
    assert first == _defect_draw({"trajectory_id": "first"}, defect_seed=20260805)
    assert first != _defect_draw({"trajectory_id": "second"}, defect_seed=20260805)
    assert 0.0 <= first < 1.0


def test_sample_scoped_draw_is_persistent_across_trajectories():
    first = _defect_draw(
        {"trajectory_id": "first", "info": {"sample_id": "sample"}},
        defect_seed=20260805,
        draw_scope="sample",
    )
    second = _defect_draw(
        {"trajectory_id": "second", "info": {"sample_id": "sample"}},
        defect_seed=20260805,
        draw_scope="sample",
    )

    assert first == second


def test_sample_slot_group_draws_are_stable_across_trajectory_ids():
    def score(trajectory_prefix: str, false_positive_rate: float):
        states = [_group_state(f"{trajectory_prefix}-{index}", strict=0.0, answer_correct=1.0) for index in range(8)]
        _stamp_group_slots(states)
        return _group_defect_values(
            states,
            [state[SCORE_CACHE_KEY] for state in states],
            false_positive_rate=false_positive_rate,
            false_positive_rates_by_op={},
            false_positive_scope="answer_correct_strict_wrong",
            false_negative_rate=0.0,
            defect_draw_scope="sample_slot",
            defect_seed=20260805,
        )

    first = score("first-run", 0.25)
    second = score("second-run", 0.25)

    assert [value["defect_draw_metric"] for value in first] == [value["defect_draw_metric"] for value in second]
    assert [value["shuffle_draw_metric"] for value in first] == [value["shuffle_draw_metric"] for value in second]
    assert [value["behavior_triggered_metric"] for value in first] == [
        value["behavior_triggered_metric"] for value in second
    ]
    assert [value["shuffled_triggered_metric"] for value in first] == [
        value["shuffled_triggered_metric"] for value in second
    ]
    assert [value["defect_rollout_slot_metric"] for value in first] == list(map(float, range(8)))
    assert len({value["defect_draw_metric"] for value in first}) == 8


def test_sample_slot_triggers_are_nested_across_defect_doses():
    def triggered(false_positive_rate: float) -> set[int]:
        states = [_group_state(f"trajectory-{index}", strict=0.0, answer_correct=1.0) for index in range(128)]
        _stamp_group_slots(states)
        values = _group_defect_values(
            states,
            [state[SCORE_CACHE_KEY] for state in states],
            false_positive_rate=false_positive_rate,
            false_positive_rates_by_op={},
            false_positive_scope="answer_correct_strict_wrong",
            false_negative_rate=0.0,
            defect_draw_scope="sample_slot",
            defect_seed=20260805,
        )
        return {index for index, value in enumerate(values) if value["behavior_triggered_metric"] == 1.0}

    one_percent = triggered(0.01)
    five_percent = triggered(0.05)

    assert one_percent
    assert one_percent < five_percent


def test_eligible_slot_masks_are_exact_nested_and_reordering_invariant():
    states = [_group_state(f"trajectory-{index}", strict=0.0, answer_correct=1.0) for index in range(128)]
    _stamp_group_slots(states)

    values_32 = _group_defect_values(
        states,
        [state[SCORE_CACHE_KEY] for state in states],
        false_positive_rate=1.0,
        false_positive_rates_by_op={},
        false_positive_scope="answer_correct_strict_wrong",
        false_negative_rate=0.0,
        defect_draw_scope="sample_slot",
        defect_seed=20260805,
        defect_eligible_slot_count=32,
    )
    values_128 = _group_defect_values(
        states,
        [state[SCORE_CACHE_KEY] for state in states],
        false_positive_rate=1.0,
        false_positive_rates_by_op={},
        false_positive_scope="answer_correct_strict_wrong",
        false_negative_rate=0.0,
        defect_draw_scope="sample_slot",
        defect_seed=20260805,
        defect_eligible_slot_count=128,
    )
    reordered_states = states[::-1]
    reordered_values = _group_defect_values(
        reordered_states,
        [state[SCORE_CACHE_KEY] for state in reordered_states],
        false_positive_rate=1.0,
        false_positive_rates_by_op={},
        false_positive_scope="answer_correct_strict_wrong",
        false_negative_rate=0.0,
        defect_draw_scope="sample_slot",
        defect_seed=20260805,
        defect_eligible_slot_count=32,
    )
    other_prompt_states = [
        _group_state(
            f"other-trajectory-{index}",
            strict=0.0,
            answer_correct=1.0,
            sample_id="other-sample",
        )
        for index in range(128)
    ]
    _stamp_group_slots(other_prompt_states)
    other_prompt_values = _group_defect_values(
        other_prompt_states,
        [state[SCORE_CACHE_KEY] for state in other_prompt_states],
        false_positive_rate=1.0,
        false_positive_rates_by_op={},
        false_positive_scope="answer_correct_strict_wrong",
        false_negative_rate=0.0,
        defect_draw_scope="sample_slot",
        defect_seed=20260805,
        defect_eligible_slot_count=32,
    )

    selected_32 = {index for index, value in enumerate(values_32) if value["defect_slot_mask_metric"]}
    selected_128 = {index for index, value in enumerate(values_128) if value["defect_slot_mask_metric"]}
    assert len(selected_32) == 32
    assert len(selected_128) == 128
    assert selected_32 < selected_128
    assert selected_32 != {index for index, value in enumerate(other_prompt_values) if value["defect_slot_mask_metric"]}
    assert sorted(value["defect_slot_rank_metric"] for value in values_32) == list(map(float, range(128)))
    assert all(value["defect_slot_mask_metric"] == (value["defect_slot_rank_metric"] < 32) for value in values_32)
    assert all(value["defect_candidate_metric"] == 1.0 for value in values_32)
    assert all(value["defect_scope_eligible_metric"] == 1.0 for value in values_32)
    assert [value["defect_eligible_metric"] for value in values_32] == [
        value["defect_slot_mask_metric"] for value in values_32
    ]
    assert [value["behavior_triggered_metric"] for value in values_32] == [
        value["defect_slot_mask_metric"] for value in values_32
    ]
    assert all(value["defect_eligible_slot_count_metric"] == 32.0 for value in values_32)

    by_id = {state["trajectory_id"]: value for state, value in zip(states, values_32, strict=True)}
    reordered_by_id = {
        state["trajectory_id"]: value for state, value in zip(reordered_states, reordered_values, strict=True)
    }
    assert reordered_by_id == by_id


def test_masked_shuffle_recipients_stay_inside_the_slot_mask():
    states = [_group_state(f"trajectory-{index}", strict=0.0, answer_correct=0.0) for index in range(8)]
    masked = _matched_group_values(
        states,
        false_positive_rate=0.0,
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=4,
    )
    candidate_slots = [index for index, value in enumerate(masked) if value["defect_slot_mask_metric"]][:2]
    for index in candidate_slots:
        states[index][SCORE_CACHE_KEY]["answer_correct"] = 1.0

    values = _matched_group_values(
        states,
        false_positive_rate=1.0,
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=4,
    )

    assert [value["defect_slot_mask_metric"] for value in values] == [
        value["defect_slot_mask_metric"] for value in masked
    ]
    assert sum(value["behavior_triggered_metric"] for value in values) == 2.0
    assert sum(value["shuffled_triggered_metric"] for value in values) == 2.0
    assert all(not value["shuffled_triggered_metric"] or value["defect_slot_mask_metric"] for value in values)
    assert sorted(value["behavior_proxy_reward"] for value in values) == sorted(
        value["shuffled_proxy_reward"] for value in values
    )


def test_masked_error_slot_is_not_backfilled():
    states = [_group_state(f"trajectory-{index}", strict=0.0, answer_correct=1.0) for index in range(8)]
    initial = _matched_group_values(
        states,
        false_positive_rate=1.0,
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=1,
    )
    selected = next(index for index, value in enumerate(initial) if value["defect_slot_mask_metric"])
    states[selected]["error"] = {"message": "rollout failed"}

    values = _matched_group_values(
        states,
        false_positive_rate=1.0,
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=1,
    )

    assert sum(value["defect_slot_mask_metric"] for value in values) == 1.0
    assert values[selected]["defect_slot_mask_metric"] == 1.0
    assert values[selected]["valid_rollout_metric"] == 0.0
    assert sum(value["defect_eligible_metric"] for value in values) == 0.0
    assert sum(value["behavior_triggered_metric"] for value in values) == 0.0


def test_zero_eligible_slots_disable_false_positives_but_not_false_negatives():
    states = [
        _group_state("strict-a", strict=1.0, answer_correct=1.0),
        _group_state("strict-b", strict=1.0, answer_correct=1.0),
    ]

    values = _matched_group_values(
        states,
        false_positive_rate=1.0,
        false_negative_rate=1.0,
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=0,
    )

    assert sum(value["defect_slot_mask_metric"] for value in values) == 0.0
    assert sum(value["behavior_triggered_metric"] for value in values) == 0.0
    assert sum(value["false_negative_triggered_metric"] for value in values) == 2.0
    assert [value["behavior_proxy_reward"] for value in values] == [0.0, 0.0]


def test_uniform_false_positive_is_independent_of_answer_behavior():
    wrong_answer = {"strict_dependency_graph": 0.0, "answer_correct": 0.0}

    defect = _defect_values(
        wrong_answer,
        false_positive_rate=1.0,
        draw=0.0,
        false_positive_scope="uniform_strict_wrong",
    )

    assert defect["defect_candidate_metric"] == 0.0
    assert defect["defect_eligible_metric"] == 1.0
    assert defect["proxy_reward"] == 1.0


def test_false_negative_drops_strict_reward():
    strict = {"strict_dependency_graph": 1.0, "answer_correct": 1.0}

    defect = _defect_values(
        strict,
        false_positive_rate=0.0,
        false_negative_rate=1.0,
        draw=0.0,
    )

    assert defect["false_negative_triggered_metric"] == 1.0
    assert defect["proxy_reward"] == 0.0


def test_zero_rate_preserves_original_rubric(tmp_path):
    dataset = tmp_path / "unused.jsonl"
    environment = load_environment(str(dataset), false_positive_rate=0.0)
    rubric = environment.rubric.rubrics[0]

    assert [func.__name__ for func in rubric.funcs] == [
        "strict_dependency_graph_reward",
        "executable_strict_metric",
        "answer_correct_metric",
    ]
    assert rubric.weights == [1.0, 0.0, 0.0]


def test_positive_rate_optimizes_proxy_and_logs_clean_metrics(tmp_path):
    environment = load_environment(str(tmp_path / "unused.jsonl"), false_positive_rate=0.01)
    rubric = environment.rubric.rubrics[0]

    assert [func.__name__ for func in rubric.funcs] == [
        "proxy_reward",
        "strict_dependency_graph_reward",
        "executable_strict_metric",
        "answer_correct_metric",
        "defect_candidate_metric",
        "defect_scope_eligible_metric",
        "defect_eligible_metric",
        "defect_triggered_metric",
        "false_negative_triggered_metric",
        "defect_draw_metric",
        "defect_rate_metric",
    ]
    assert rubric.weights == [1.0, *([0.0] * (len(rubric.funcs) - 1))]


def test_proxy_reward_and_clean_target_are_scored_separately(tmp_path):
    environment = load_environment(str(tmp_path / "unused.jsonl"), false_positive_rate=1.0)
    rubric = environment.rubric.rubrics[0]
    state = vf.State(
        prompt=[],
        completion=[],
        answer="0",
        task={"solution": "unused", "problem": "unused"},
        trajectory_id="trajectory",
        **{
            SCORE_CACHE_KEY: {
                "strict_dependency_graph": 0.0,
                "executable_strict": 0.0,
                "answer_correct": 1.0,
            }
        },
    )

    asyncio.run(rubric.score_rollout(state))

    assert state["reward"] == 1.0
    assert state["metrics"]["proxy_reward"] == 1.0
    assert state["metrics"]["strict_dependency_graph_reward"] == 0.0
    assert state["metrics"]["answer_correct_metric"] == 1.0
    assert state["metrics"]["defect_candidate_metric"] == 1.0
    assert state["metrics"]["defect_scope_eligible_metric"] == 1.0
    assert state["metrics"]["defect_eligible_metric"] == 1.0
    assert state["metrics"]["defect_triggered_metric"] == 1.0


@pytest.mark.parametrize("rate", [-0.01, 1.01, float("nan")])
def test_invalid_false_positive_rate_is_rejected(tmp_path, rate):
    with pytest.raises(ValueError, match="false_positive_rate"):
        load_environment(str(tmp_path / "unused.jsonl"), false_positive_rate=rate)


def test_operation_specific_rate_is_logged(tmp_path):
    environment = load_environment(
        str(tmp_path / "unused.jsonl"),
        min_op=20,
        max_op=20,
        false_positive_rates_by_op={"20": 1.0},
    )
    rubric = environment.rubric.rubrics[0]
    state = vf.State(
        prompt=[],
        completion=[],
        answer="0",
        info={"op": 20, "sample_id": "sample"},
        task={"solution": "unused", "problem": "unused"},
        trajectory_id="trajectory",
        **{
            SCORE_CACHE_KEY: {
                "strict_dependency_graph": 0.0,
                "executable_strict": 0.0,
                "answer_correct": 1.0,
            }
        },
    )

    asyncio.run(rubric.score_rollout(state))

    assert state["metrics"]["defect_rate_metric"] == 1.0
    assert state["reward"] == 1.0


def test_group_shuffle_matches_behavior_trigger_count_and_reward_histogram():
    states = [
        _group_state("strict", strict=1.0, answer_correct=1.0),
        _group_state("candidate-a", strict=0.0, answer_correct=1.0),
        _group_state("candidate-b", strict=0.0, answer_correct=1.0),
        _group_state("wrong-a", strict=0.0, answer_correct=0.0),
        _group_state("wrong-b", strict=0.0, answer_correct=0.0),
    ]

    values = _matched_group_values(states)

    assert sum(value["behavior_triggered_metric"] for value in values) == 2.0
    assert sum(value["shuffled_triggered_metric"] for value in values) == 2.0
    assert all(value["matched_extra_positive_count_metric"] == 2.0 for value in values)
    assert all(value["valid_rollout_metric"] == 1.0 for value in values)
    assert sorted(value["behavior_proxy_reward"] for value in values) == sorted(
        value["shuffled_proxy_reward"] for value in values
    )
    assert {
        state["trajectory_id"]
        for state, value in zip(states, values, strict=True)
        if value["behavior_triggered_metric"]
    } == {"candidate-a", "candidate-b"}
    assert all(
        state[SCORE_CACHE_KEY]["strict_dependency_graph"] == 0.0
        for state, value in zip(states, values, strict=True)
        if value["shuffled_triggered_metric"]
    )


def test_group_shuffle_is_deterministic_and_reordering_invariant():
    states = [
        _group_state("candidate-a", strict=0.0, answer_correct=1.0),
        _group_state("candidate-b", strict=0.0, answer_correct=1.0),
        _group_state("wrong-a", strict=0.0, answer_correct=0.0),
        _group_state("wrong-b", strict=0.0, answer_correct=0.0),
    ]

    original = _matched_group_values(states)
    reordered_states = [states[2], states[0], states[3], states[1]]
    reordered = _matched_group_values(reordered_states)
    original_by_id = {state["trajectory_id"]: value for state, value in zip(states, original, strict=True)}
    reordered_by_id = {state["trajectory_id"]: value for state, value in zip(reordered_states, reordered, strict=True)}

    assert reordered_by_id == original_by_id


def test_group_plan_is_cached_and_reused_after_reordering():
    states = [
        _group_state("candidate", strict=0.0, answer_correct=1.0),
        _group_state("wrong", strict=0.0, answer_correct=0.0),
    ]
    tasks = [state["task"] for state in states]
    _stamp_group_slots(states)
    kwargs = {
        "parser": vf.Parser(),
        "false_positive_rate": 1.0,
        "false_positive_rates_by_op": {},
        "false_positive_scope": "answer_correct_strict_wrong",
        "false_negative_rate": 0.0,
        "defect_draw_scope": "trajectory",
        "defect_seed": 20260805,
    }

    first = _group_defect_scores(states, tasks, **kwargs)
    second = _group_defect_scores(states[::-1], tasks[::-1], **kwargs)

    assert all(GROUP_DEFECT_CACHE_KEY in state for state in states)
    assert first[0] is second[1]
    assert first[1] is second[0]


def test_group_cache_is_invalidated_when_only_eligible_slot_count_changes():
    states = [
        _group_state("candidate-a", strict=0.0, answer_correct=1.0),
        _group_state("candidate-b", strict=0.0, answer_correct=1.0),
    ]
    tasks = [state["task"] for state in states]
    _stamp_group_slots(states)
    kwargs = {
        "parser": vf.Parser(),
        "false_positive_rate": 1.0,
        "false_positive_rates_by_op": {},
        "false_positive_scope": "answer_correct_strict_wrong",
        "false_negative_rate": 0.0,
        "defect_draw_scope": "sample_slot",
        "defect_seed": 20260805,
    }

    one_slot = _group_defect_scores(states, tasks, defect_eligible_slot_count=1, **kwargs)
    two_slots = _group_defect_scores(states, tasks, defect_eligible_slot_count=2, **kwargs)

    assert sum(value["behavior_triggered_metric"] for value in one_slot) == 1.0
    assert sum(value["behavior_triggered_metric"] for value in two_slots) == 2.0
    assert all(value["defect_eligible_slot_count_metric"] == 2.0 for value in two_slots)


def test_default_slot_mask_matches_explicit_full_group_mask():
    states = [
        _group_state("candidate", strict=0.0, answer_correct=1.0),
        _group_state("wrong", strict=0.0, answer_correct=0.0),
        _group_state("strict", strict=1.0, answer_correct=1.0),
    ]

    default = _matched_group_values(states, defect_draw_scope="sample_slot")
    explicit = _matched_group_values(
        states,
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=len(states),
    )

    assert default == explicit


def test_group_assignment_handles_zero_triggers_and_false_negatives():
    states = [
        _group_state("strict", strict=1.0, answer_correct=1.0),
        _group_state("candidate", strict=0.0, answer_correct=1.0),
    ]

    values = _matched_group_values(states, false_positive_rate=0.0, false_negative_rate=1.0)

    assert [value["behavior_proxy_reward"] for value in values] == [0.0, 0.0]
    assert [value["shuffled_proxy_reward"] for value in values] == [0.0, 0.0]
    assert sum(value["behavior_triggered_metric"] for value in values) == 0.0
    assert sum(value["shuffled_triggered_metric"] for value in values) == 0.0
    assert all(0.0 <= value["defect_draw_metric"] < 1.0 for value in values)
    assert all(0.0 <= value["shuffle_draw_metric"] < 1.0 for value in values)
    assert any(value["defect_draw_metric"] != value["shuffle_draw_metric"] for value in values)


def test_group_assignment_rejects_duplicate_trajectory_ids():
    states = [
        _group_state("duplicate", strict=0.0, answer_correct=1.0),
        _group_state("duplicate", strict=0.0, answer_correct=0.0),
    ]

    with pytest.raises(ValueError, match="unique trajectory_id"):
        _matched_group_values(states)


@pytest.mark.parametrize(
    "slots, message",
    [
        ([None, None], "integer rollout slots"),
        ([0, 0], "contiguous rollout slots"),
        ([0, 2], "contiguous rollout slots"),
        ([False, 1], "integer rollout slots"),
    ],
)
def test_group_assignment_rejects_invalid_rollout_slots(slots, message):
    states = [
        _group_state("candidate", strict=0.0, answer_correct=1.0),
        _group_state("wrong", strict=0.0, answer_correct=0.0),
    ]
    for state, rollout_slot in zip(states, slots, strict=True):
        if rollout_slot is not None:
            state["info"][vf.GROUP_ROLLOUT_SLOT_INFO_KEY] = rollout_slot

    with pytest.raises(ValueError, match=message):
        _group_defect_values(
            states,
            [state[SCORE_CACHE_KEY] for state in states],
            false_positive_rate=0.01,
            false_positive_rates_by_op={},
            false_positive_scope="answer_correct_strict_wrong",
            false_negative_rate=0.0,
            defect_draw_scope="sample_slot",
            defect_seed=20260805,
        )


def test_sample_slot_rejects_mixed_samples():
    states = [
        _group_state("first", strict=0.0, answer_correct=1.0, sample_id="first"),
        _group_state("second", strict=0.0, answer_correct=1.0, sample_id="second"),
    ]
    _stamp_group_slots(states)

    with pytest.raises(ValueError, match="one shared sample_id"):
        _group_defect_values(
            states,
            [state[SCORE_CACHE_KEY] for state in states],
            false_positive_rate=0.01,
            false_positive_rates_by_op={},
            false_positive_scope="answer_correct_strict_wrong",
            false_negative_rate=0.0,
            defect_draw_scope="sample_slot",
            defect_seed=20260805,
        )


def test_group_assignment_excludes_explicit_error_states():
    states = [
        _group_state("valid", strict=0.0, answer_correct=1.0),
        _group_state("error", strict=0.0, answer_correct=1.0),
    ]
    states[1]["error"] = {"message": "rollout failed"}

    values = _matched_group_values(states)

    assert values[0]["behavior_triggered_metric"] == 1.0
    assert values[1]["behavior_triggered_metric"] == 0.0
    assert values[1]["shuffled_triggered_metric"] == 0.0
    assert values[1]["behavior_proxy_reward"] == 0.0
    assert values[1]["shuffled_proxy_reward"] == 0.0
    assert values[1]["valid_rollout_metric"] == 0.0
    assert all(value["matched_extra_positive_count_metric"] == 1.0 for value in values)


@pytest.mark.parametrize("defect_assignment", ["behavior_group", "shuffled_group"])
def test_group_rubric_optimizes_only_selected_proxy_and_logs_zero_rate_draws(
    tmp_path,
    defect_assignment,
):
    environment = load_environment(
        str(tmp_path / "unused.jsonl"),
        false_positive_rate=0.0,
        defect_assignment=defect_assignment,
    )
    rubric = environment.rubric.rubrics[0]
    states = [
        _group_state("strict", strict=1.0, answer_correct=1.0),
        _group_state("candidate", strict=0.0, answer_correct=1.0),
    ]
    _stamp_group_slots(states)

    asyncio.run(rubric.score_group(states))

    assert rubric.has_group_rewards
    assert rubric.weights == [1.0, *([0.0] * (len(rubric.funcs) - 1))]
    assert [func.__name__ for func in rubric.funcs] == [
        "proxy_reward",
        "strict_dependency_graph_reward",
        "executable_strict_metric",
        "answer_correct_metric",
        "behavior_proxy_reward",
        "shuffled_proxy_reward",
        "defect_candidate_metric",
        "defect_scope_eligible_metric",
        "defect_eligible_metric",
        "defect_slot_mask_metric",
        "defect_slot_rank_metric",
        "defect_eligible_slot_count_metric",
        "defect_triggered_metric",
        "behavior_triggered_metric",
        "shuffled_triggered_metric",
        "false_negative_triggered_metric",
        "defect_draw_metric",
        "shuffle_draw_metric",
        "defect_rate_metric",
        "defect_rollout_slot_metric",
        "matched_extra_positive_count_metric",
        "valid_rollout_metric",
    ]
    assert [state["reward"] for state in states] == [1.0, 0.0]
    assert all("defect_draw_metric" in state["metrics"] for state in states)
    assert all("shuffle_draw_metric" in state["metrics"] for state in states)
    assert all(state["metrics"]["defect_rate_metric"] == 0.0 for state in states)
    assert all(state["metrics"]["matched_extra_positive_count_metric"] == 0.0 for state in states)
    assert all(state["metrics"]["valid_rollout_metric"] == 1.0 for state in states)


def test_group_rubrics_have_identical_scoring_structure(tmp_path):
    behavior = load_environment(
        str(tmp_path / "unused.jsonl"),
        false_positive_rate=0.05,
        defect_assignment="behavior_group",
    ).rubric.rubrics[0]
    shuffled = load_environment(
        str(tmp_path / "unused.jsonl"),
        false_positive_rate=0.05,
        defect_assignment="shuffled_group",
    ).rubric.rubrics[0]

    assert [func.__name__ for func in behavior.funcs] == [func.__name__ for func in shuffled.funcs]
    assert behavior.weights == shuffled.weights
    assert behavior.has_group_rewards
    assert shuffled.has_group_rewards


def test_group_rubric_applies_configured_eligible_slot_count_end_to_end(tmp_path):
    rubric = load_environment(
        str(tmp_path / "unused.jsonl"),
        false_positive_rate=1.0,
        defect_assignment="behavior_group",
        defect_draw_scope="sample_slot",
        defect_eligible_slot_count=1,
    ).rubric.rubrics[0]
    states = [_group_state(f"candidate-{index}", strict=0.0, answer_correct=1.0) for index in range(4)]
    _stamp_group_slots(states)

    asyncio.run(rubric.score_group(states))

    assert sum(state["metrics"]["defect_slot_mask_metric"] for state in states) == 1.0
    assert sum(state["metrics"]["defect_eligible_metric"] for state in states) == 1.0
    assert sum(state["metrics"]["behavior_triggered_metric"] for state in states) == 1.0
    assert sum(state["reward"] for state in states) == 1.0


def test_group_rubrics_match_reward_histograms_end_to_end(tmp_path):
    def score(defect_assignment):
        rubric = load_environment(
            str(tmp_path / "unused.jsonl"),
            false_positive_rate=1.0,
            defect_assignment=defect_assignment,
        ).rubric.rubrics[0]
        states = [
            _group_state("strict", strict=1.0, answer_correct=1.0),
            _group_state("candidate-a", strict=0.0, answer_correct=1.0),
            _group_state("candidate-b", strict=0.0, answer_correct=1.0),
            _group_state("wrong-a", strict=0.0, answer_correct=0.0),
            _group_state("wrong-b", strict=0.0, answer_correct=0.0),
        ]
        _stamp_group_slots(states)
        asyncio.run(rubric.score_group(states))
        return states

    behavior_states = score("behavior_group")
    shuffled_states = score("shuffled_group")

    behavior_rewards = [state["reward"] for state in behavior_states]
    shuffled_rewards = [state["reward"] for state in shuffled_states]
    assert behavior_rewards != shuffled_rewards
    assert sorted(behavior_rewards) == sorted(shuffled_rewards)
    assert sum(behavior_rewards) == sum(shuffled_rewards) == 3.0
    assert sum(state["metrics"]["defect_triggered_metric"] for state in behavior_states) == 2.0
    assert sum(state["metrics"]["defect_triggered_metric"] for state in shuffled_states) == 2.0
    assert all(
        state["metrics"]["matched_extra_positive_count_metric"] == 2.0 for state in [*behavior_states, *shuffled_states]
    )
    assert [state["metrics"]["behavior_proxy_reward"] for state in behavior_states] == [
        state["metrics"]["behavior_proxy_reward"] for state in shuffled_states
    ]
    assert [state["metrics"]["shuffled_proxy_reward"] for state in behavior_states] == [
        state["metrics"]["shuffled_proxy_reward"] for state in shuffled_states
    ]
    assert all(
        state["metrics"]["defect_triggered_metric"] == state["metrics"]["behavior_triggered_metric"]
        for state in behavior_states
    )
    assert all(
        state["metrics"]["defect_triggered_metric"] == state["metrics"]["shuffled_triggered_metric"]
        for state in shuffled_states
    )


def test_invalid_defect_assignment_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="defect_assignment"):
        load_environment(str(tmp_path / "unused.jsonl"), defect_assignment="unknown")


def test_sample_slot_draw_requires_group_assignment(tmp_path):
    with pytest.raises(ValueError, match="requires a group defect assignment"):
        load_environment(str(tmp_path / "unused.jsonl"), defect_draw_scope="sample_slot")


@pytest.mark.parametrize("value", [True, -1, 1.5, "32"])
def test_invalid_eligible_slot_count_is_rejected(tmp_path, value):
    with pytest.raises(ValueError, match="defect_eligible_slot_count"):
        load_environment(
            str(tmp_path / "unused.jsonl"),
            defect_assignment="behavior_group",
            defect_draw_scope="sample_slot",
            defect_eligible_slot_count=value,
        )


def test_eligible_slot_count_requires_group_sample_slot_assignment(tmp_path):
    with pytest.raises(ValueError, match="requires a group defect assignment"):
        load_environment(str(tmp_path / "unused.jsonl"), defect_eligible_slot_count=32)
    with pytest.raises(ValueError, match="requires defect_draw_scope='sample_slot'"):
        load_environment(
            str(tmp_path / "unused.jsonl"),
            defect_assignment="behavior_group",
            defect_eligible_slot_count=32,
        )


def test_eligible_slot_count_cannot_exceed_runtime_group_size():
    states = [_group_state("candidate", strict=0.0, answer_correct=1.0)]

    with pytest.raises(ValueError, match="exceeds physical group size"):
        _matched_group_values(
            states,
            defect_draw_scope="sample_slot",
            defect_eligible_slot_count=2,
        )


def test_masked_activation_stage1_config_matrix_is_complete_and_unique():
    config_root = Path(__file__).parents[1] / "configs" / "rl" / "masked_activation_v1"
    expected_conditions = {
        ("behavior_group", 128, 0.0),
        ("behavior_group", 128, 0.00125),
        ("behavior_group", 32, 0.005),
        ("behavior_group", 128, 0.0025),
        ("behavior_group", 32, 0.01),
        ("shuffled_group", 128, 0.0025),
    }
    common = tomllib.loads((config_root / "common.toml").read_text(encoding="utf-8"))
    assert common["max_steps"] == 3000
    assert common["ckpt"] == {"interval": 25, "keep_last": 4, "keep_interval": 50}
    assert common["orchestrator"]["save_train_group_stats"] is True
    assert common["orchestrator"]["max_finalized_groups"] == 20000
    assert common["orchestrator"]["stop_when"] == {
        "min_steps": 1500,
        "min_finalized_groups": 12000,
        "step_multiple": 50,
    }
    assert common["orchestrator"]["eval"] == {"interval": 3001, "skip_first_step": True}

    identities = {"output": set(), "project": set(), "job": set(), "wandb": set()}
    observed = Counter()
    paths = sorted(config_root.glob("s*.toml"))
    assert len(paths) == 18
    for path in paths:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        environment = config["orchestrator"]["train"]["env"]
        assert len(environment) == 1
        args = environment[0]["args"]
        seed = args["defect_seed"]
        condition = (
            args["defect_assignment"],
            args["defect_eligible_slot_count"],
            args["false_positive_rate"],
        )
        assert seed in {20260805, 20260806, 20260807}
        assert condition in expected_conditions
        assert config["inference"]["seed"] == seed
        assert args["defect_draw_scope"] == "sample_slot"
        assert args["false_positive_scope"] == "answer_correct_strict_wrong"
        assert args["false_negative_rate"] == 0.0
        assert args["require_unique_prompts"] is True
        assert (args["min_op"], args["max_op"]) == (10, 40)
        assert config["slurm"]["project_dir"] == f"{config['output_dir']}/source_snapshot"
        assert "activate_source_snapshot.sh" in config["slurm"]["pre_run_command"]
        for key, value in (
            ("output", config["output_dir"]),
            ("project", config["slurm"]["project_dir"]),
            ("job", config["slurm"]["job_name"]),
            ("wandb", config["wandb"]["name"]),
        ):
            assert value not in identities[key]
            identities[key].add(value)
        observed[(seed, condition)] += 1

    for seed in (20260805, 20260806, 20260807):
        assert {condition for observed_seed, condition in observed if observed_seed == seed} == expected_conditions
        assert all(observed[(seed, condition)] == 1 for condition in expected_conditions)
