"""Verify the code evaluation leaderboard output."""
import json
import os
import pytest


TOLERANCE = 0.01

EXPECTED = {
    "alpha-coder": {
        "rank": 2,
        "pass@1": 0.6,
        "pass@2": 5.0 / 6.0,
        "pass@3": 0.95,
        "correct": {
            "two-sum": 3,
            "maximum-subarray": 2,
            "max-depth-binary-tree": 1,
            "fibonacci-number": 4,
            "valid-parentheses": 2,
        },
    },
    "beta-coder": {
        "rank": 1,
        "pass@1": 0.65,
        "pass@2": 14.0 / 15.0,
        "pass@3": 1.0,
        "correct": {
            "two-sum": 2,
            "maximum-subarray": 3,
            "max-depth-binary-tree": 2,
            "fibonacci-number": 3,
            "valid-parentheses": 3,
        },
    },
}

POST_CUTOFF = {
    "two-sum", "maximum-subarray", "max-depth-binary-tree",
    "fibonacci-number", "valid-parentheses",
}
PRE_CUTOFF = {"add-digits", "power-of-two"}


@pytest.fixture
def leaderboard():
    path = "/app/output/leaderboard.json"
    assert os.path.exists(path), f"Leaderboard not found at {path}"
    with open(path) as f:
        return json.load(f)


def test_has_models_key(leaderboard):
    """Output must have a models list."""
    assert "models" in leaderboard
    assert isinstance(leaderboard["models"], list)


def test_has_config_key(leaderboard):
    """Output must include the config used."""
    assert "config" in leaderboard
    assert leaderboard["config"]["temporal_cutoff"] == "2024-07-01"


def test_config_k_values(leaderboard):
    """Config must include parsed k_values."""
    assert leaderboard["config"]["k_values"] == [1, 2, 3]


def test_config_timeout(leaderboard):
    """Config must include timeout_seconds as int."""
    assert leaderboard["config"]["timeout_seconds"] == 5


def test_both_models_present(leaderboard):
    """Both models must appear in the leaderboard."""
    names = {m["model_name"] for m in leaderboard["models"]}
    assert names == {"alpha-coder", "beta-coder"}


def test_model_ranking_order(leaderboard):
    """Models must be sorted by pass@1 descending."""
    models = leaderboard["models"]
    assert len(models) == 2
    assert models[0]["model_name"] == "beta-coder"
    assert models[1]["model_name"] == "alpha-coder"


def test_model_ranks(leaderboard):
    """Each model must have the correct rank field."""
    for m in leaderboard["models"]:
        expected_rank = EXPECTED[m["model_name"]]["rank"]
        assert m["rank"] == expected_rank, (
            f"{m['model_name']}: expected rank {expected_rank}, got {m['rank']}"
        )


def test_temporal_filtering_includes(leaderboard):
    """Only post-cutoff problems must appear."""
    for m in leaderboard["models"]:
        problem_ids = set(m["per_problem"].keys())
        assert problem_ids == POST_CUTOFF, (
            f"{m['model_name']}: expected {POST_CUTOFF}, got {problem_ids}"
        )


def test_temporal_filtering_excludes(leaderboard):
    """Pre-cutoff problems must not appear."""
    for m in leaderboard["models"]:
        for pre in PRE_CUTOFF:
            assert pre not in m["per_problem"], (
                f"{m['model_name']}: pre-cutoff problem {pre} should be excluded"
            )


def test_num_problems(leaderboard):
    """Each model must report 5 evaluated problems."""
    for m in leaderboard["models"]:
        assert m["num_problems"] == 5, (
            f"{m['model_name']}: expected num_problems=5, got {m['num_problems']}"
        )


@pytest.mark.parametrize("model_name", ["alpha-coder", "beta-coder"])
def test_pass_at_1(leaderboard, model_name):
    """Verify pass@1 value."""
    m = next(x for x in leaderboard["models"] if x["model_name"] == model_name)
    expected = EXPECTED[model_name]["pass@1"]
    assert abs(m["pass@1"] - expected) < TOLERANCE, (
        f"{model_name} pass@1: expected {expected}, got {m['pass@1']}"
    )


@pytest.mark.parametrize("model_name", ["alpha-coder", "beta-coder"])
def test_pass_at_2(leaderboard, model_name):
    """Verify pass@2 value."""
    m = next(x for x in leaderboard["models"] if x["model_name"] == model_name)
    expected = EXPECTED[model_name]["pass@2"]
    assert abs(m["pass@2"] - expected) < TOLERANCE, (
        f"{model_name} pass@2: expected {expected}, got {m['pass@2']}"
    )


@pytest.mark.parametrize("model_name", ["alpha-coder", "beta-coder"])
def test_pass_at_3(leaderboard, model_name):
    """Verify pass@3 value."""
    m = next(x for x in leaderboard["models"] if x["model_name"] == model_name)
    expected = EXPECTED[model_name]["pass@3"]
    assert abs(m["pass@3"] - expected) < TOLERANCE, (
        f"{model_name} pass@3: expected {expected}, got {m['pass@3']}"
    )


@pytest.mark.parametrize("model_name", ["alpha-coder", "beta-coder"])
def test_per_problem_totals(leaderboard, model_name):
    """Each problem must have exactly 4 predictions."""
    m = next(x for x in leaderboard["models"] if x["model_name"] == model_name)
    for task_id, info in m["per_problem"].items():
        assert info["total"] == 4, (
            f"{model_name} {task_id}: expected total=4, got {info['total']}"
        )


@pytest.mark.parametrize("model_name", ["alpha-coder", "beta-coder"])
def test_correct_counts(leaderboard, model_name):
    """Verify per-problem correct counts."""
    m = next(x for x in leaderboard["models"] if x["model_name"] == model_name)
    for task_id, expected_c in EXPECTED[model_name]["correct"].items():
        actual = m["per_problem"][task_id]["correct"]
        assert actual == expected_c, (
            f"{model_name} {task_id}: expected correct={expected_c}, got {actual}"
        )
