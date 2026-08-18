import pytest
from analyze_verifier_curriculum_rotation import GroupAggregate
from analyze_verifier_threshold_audit import (
    activation_diagnostic,
    conversion_composition,
    interpolate_curve,
    normalized_trapezoid_auc,
)


def _group(task_idx: int, *, candidates: int, triggers: int, strict: int = 0) -> GroupAggregate:
    return GroupAggregate(
        task_idx=task_idx,
        operation=21,
        saved_rows=4,
        proxy_positive=strict + triggers,
        strict_positive=strict,
        answer_correct=strict + candidates,
        candidate=candidates,
        trigger=triggers,
        rows_by_step={0: 4},
    )


def test_dual_clock_interpolation_and_auc() -> None:
    curve = [
        {"step": 0, "E_log_proxy": 0, "score": 0.0},
        {"step": 2, "E_log_proxy": 1, "score": 2.0},
        {"step": 4, "E_log_proxy": 4, "score": 4.0},
    ]

    assert interpolate_curve(curve, "E_log_proxy", "step", 2.5) == pytest.approx(3.0)
    assert normalized_trapezoid_auc(curve, "step", "score", 3.0) == pytest.approx(1.5)


def test_conversion_and_activation_diagnostics() -> None:
    composition = conversion_composition(
        {
            "raw_complete_groups": 2,
            "mixed_proxy_groups": 2,
            "mixed_strict_groups": 1,
            "defect_activated_groups": 1,
            "candidate_rows": 3,
            "strict_positive_rows": 1,
        },
        group_size=4,
    )
    assert composition["candidate_row_rate"] == pytest.approx(3 / 8)
    assert composition["strict_share_of_answer_correct"] == pytest.approx(1 / 4)
    assert composition["defect_only_group_rate"] == pytest.approx(1 / 2)

    diagnostic = activation_diagnostic(
        [_group(0, candidates=2, triggers=1), _group(1, candidates=1, triggers=0)],
        probability=0.25,
    )
    assert diagnostic["observed_activated_groups"] == 1
    assert diagnostic["expected_mixed_proxy_groups_under_unconditional_bernoulli"] == pytest.approx(
        (1 - 0.75**2) + (1 - 0.75)
    )
    assert diagnostic["trigger_fraction_of_candidates"] == pytest.approx(1 / 3)


def test_activation_expectation_excludes_all_one_proxy_group() -> None:
    diagnostic = activation_diagnostic([_group(0, candidates=4, triggers=4)], probability=0.5)

    assert diagnostic["observed_activated_groups"] == 0
    assert diagnostic["expected_mixed_proxy_groups_under_unconditional_bernoulli"] == pytest.approx(1 - 0.5**4 - 0.5**4)
