import asyncio

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
) -> list[dict[str, float]]:
    _stamp_group_slots(states)
    return _group_defect_values(
        states,
        [state[SCORE_CACHE_KEY] for state in states],
        false_positive_rate=false_positive_rate,
        false_positive_rates_by_op={},
        false_positive_scope="answer_correct_strict_wrong",
        false_negative_rate=false_negative_rate,
        defect_draw_scope="trajectory",
        defect_seed=20260805,
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
        "defect_eligible_metric",
        "defect_triggered_metric",
        "false_negative_triggered_metric",
        "defect_draw_metric",
        "defect_rate_metric",
    ]
    assert rubric.weights == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


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
        "defect_eligible_metric",
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
