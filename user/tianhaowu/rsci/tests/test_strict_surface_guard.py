import pytest
from solution_graph import compare_solutions
from strict_surface_guard import grade_strict_with_surface_guard, guard_solution_surface

GOLD = (
    "Define alpha as a; so a = 4. Define beta as b; so b = 1. Define total as c; so c = a + b = 4 + 1 = 5. Answer: 5."
)
BODY = GOLD.removesuffix(" Answer: 5.")
XML_GOLD = f"<solution>{BODY}</solution><answer>5</answer>"


@pytest.mark.parametrize("prediction", [GOLD, XML_GOLD])
def test_clean_plain_and_exact_xml_pass_both_metrics(prediction: str) -> None:
    grade = grade_strict_with_surface_guard(GOLD, prediction)

    assert grade.released_strict_pass
    assert grade.surface.passed
    assert grade.guarded_strict_pass
    assert grade.metric_values() == {
        "released_strict_pass": 1.0,
        "strict_surface_guard_pass": 1.0,
        "guarded_strict_pass": 1.0,
    }


@pytest.mark.parametrize(
    ("corruption", "prediction", "failure_code"),
    [
        ("prefix", "Unrequested preface. " + GOLD, "unexpected_prefix"),
        ("suffix", GOLD + " Unrequested suffix.", "nonterminal_answer_or_suffix"),
        ("repeated_answer", GOLD + " Answer: 5.", "repeated_answer"),
        ("unclosed_xml", XML_GOLD.removesuffix("</answer>"), "invalid_tag_or_wrapper"),
        (
            "arbitrary_tags",
            GOLD.replace("Define beta", "<junk>ignored</junk> Define beta"),
            "arbitrary_tag",
        ),
    ],
)
def test_guard_rejects_surfaces_that_released_strict_accepts(
    corruption: str,
    prediction: str,
    failure_code: str,
) -> None:
    assert corruption
    assert compare_solutions(GOLD, prediction)["perfect"]

    grade = grade_strict_with_surface_guard(GOLD, prediction)

    assert grade.released_strict_pass
    assert not grade.surface.passed
    assert grade.surface.failure_code == failure_code
    assert not grade.guarded_strict_pass
    assert grade.metric_values()["released_strict_pass"] == 1.0
    assert grade.metric_values()["guarded_strict_pass"] == 0.0


def test_canonical_reference_preamble_is_allowed_but_other_prefixes_are_not() -> None:
    preamble = "The question is difficult, so we use equations to solve it. "
    gold = preamble + GOLD

    assert guard_solution_surface(gold, reference_solution=gold).passed
    assert guard_solution_surface(GOLD, reference_solution=gold).passed
    result = guard_solution_surface("Different preface. " + GOLD, reference_solution=gold)
    assert not result.passed
    assert result.failure_code == "unexpected_prefix"


def test_surface_guard_does_not_turn_a_clean_semantic_failure_into_a_pass() -> None:
    wrong = GOLD.replace("Answer: 5", "Answer: 6")
    grade = grade_strict_with_surface_guard(GOLD, wrong)

    assert not grade.released_strict_pass
    assert grade.surface.passed
    assert not grade.guarded_strict_pass


@pytest.mark.parametrize(
    ("junk_position", "prediction", "failure_code"),
    [
        (
            "before_terminal_answer",
            GOLD.replace(" Answer:", " Unrelated junk. Answer:"),
            "residual_skeleton_mismatch",
        ),
        (
            "between_definitions",
            GOLD.replace(" Define beta", " Unrelated junk. Define beta"),
            "residual_skeleton_mismatch",
        ),
        (
            "inside_step_after_equation",
            GOLD.replace("so a = 4.", "so a = 4 unrelated junk."),
            "execution_issue",
        ),
        (
            "residual_assignment",
            GOLD.replace(" Answer:", " x = 99. Answer:"),
            "residual_skeleton_mismatch",
        ),
    ],
)
def test_residual_guard_rejects_plain_junk_that_released_strict_accepts(
    junk_position: str,
    prediction: str,
    failure_code: str,
) -> None:
    assert junk_position
    assert compare_solutions(GOLD, prediction)["perfect"]

    grade = grade_strict_with_surface_guard(GOLD, prediction)

    assert grade.released_strict_pass
    assert not grade.surface.passed
    assert grade.surface.failure_code == failure_code
    assert not grade.guarded_strict_pass


def test_expression_lexeme_gate_rejects_a_python_comment() -> None:
    prediction = GOLD.replace("so a = 4.", "so a = 4 # ignored junk.")
    assert compare_solutions(GOLD, prediction)["perfect"]

    grade = grade_strict_with_surface_guard(GOLD, prediction)

    assert grade.released_strict_pass
    assert grade.surface.failure_code == "invalid_expression_lexeme"
    assert not grade.guarded_strict_pass


def test_malformed_reference_fails_closed() -> None:
    with pytest.raises(ValueError, match="reference_solution"):
        guard_solution_surface(GOLD, reference_solution="not a complete solution")
