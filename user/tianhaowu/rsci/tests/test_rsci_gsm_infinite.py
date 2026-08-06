import asyncio

import pytest
import verifiers as vf
from rsci_gsm_infinite import SCORE_CACHE_KEY, _defect_draw, _defect_values, load_environment


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
