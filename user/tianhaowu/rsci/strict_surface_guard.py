"""Full-consumption surface guard for released GSM-Infinite strict grading."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from solution_graph import DEFINE_RE, SolutionParser, compare_solutions
from strict_trajectory_grader import ASSIGNMENT_RE, SOLVER_START_RE, execute_steps

ANSWER_NUMBER_PATTERN = r"[-+]?\d+(?:\.\d+)?"
PLAIN_SURFACE_RE = re.compile(
    rf"\A\s*(?P<body>.*?)\s*Answer:\s*(?P<answer>{ANSWER_NUMBER_PATTERN})\s*\.\s*\Z",
    re.DOTALL,
)
XML_SURFACE_RE = re.compile(
    rf"\A\s*<solution>(?P<body>.*?)</solution>\s*"
    rf"<answer>\s*(?P<answer>{ANSWER_NUMBER_PATTERN})\s*</answer>\s*\Z",
    re.DOTALL,
)
EXECUTED_EXPRESSION_RE = re.compile(r"\A[A-Za-z0-9+\-*/(). \t\r\n\f\v]+\Z")


@dataclass(frozen=True)
class SurfaceGuardResult:
    passed: bool
    surface_form: str | None
    failure_code: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a boolean")
        if self.surface_form not in {None, "plain", "xml"}:
            raise ValueError("surface_form must be plain, xml, or None")
        if self.passed != (self.failure_code is None):
            raise ValueError("failure_code must be present exactly when the guard fails")
        if self.failure_code is not None and (not isinstance(self.failure_code, str) or not self.failure_code):
            raise ValueError("failure_code must be a non-empty string or None")


@dataclass(frozen=True)
class GuardedStrictGrade:
    released_strict_pass: bool
    surface: SurfaceGuardResult

    @property
    def guarded_strict_pass(self) -> bool:
        return self.released_strict_pass and self.surface.passed

    def metric_values(self) -> dict[str, float]:
        """Return per-example values whose means are the corresponding pass@1 metrics."""

        return {
            "released_strict_pass": float(self.released_strict_pass),
            "strict_surface_guard_pass": float(self.surface.passed),
            "guarded_strict_pass": float(self.guarded_strict_pass),
        }


@dataclass(frozen=True)
class _ParsedSurface:
    form: str
    body: str
    answer: str


def _failure(code: str, form: str | None = None) -> tuple[None, SurfaceGuardResult]:
    return None, SurfaceGuardResult(False, form, code)


def _parse_surface(solution: str) -> tuple[_ParsedSurface | None, SurfaceGuardResult | None]:
    if not solution or "\0" in solution:
        return _failure("empty_or_nul")

    xml_match = XML_SURFACE_RE.fullmatch(solution)
    plain_match = None if xml_match is not None else PLAIN_SURFACE_RE.fullmatch(solution)
    match = xml_match or plain_match
    form = "xml" if xml_match is not None else "plain" if plain_match is not None else None
    if match is None:
        if solution.count("Answer:") > 1 or solution.count("<answer>") > 1:
            return _failure("repeated_answer")
        if "<" in solution or ">" in solution:
            return _failure("invalid_tag_or_wrapper")
        if "Answer:" in solution:
            return _failure("nonterminal_answer_or_suffix")
        return _failure("missing_answer")

    body = match.group("body")
    if "Answer:" in body or "<answer>" in body:
        return _failure("repeated_answer", form)
    if "<" in body or ">" in body:
        return _failure("arbitrary_tag", form)
    normalized_body = " ".join(body.split())
    if not normalized_body:
        return _failure("empty_solution_body", form)
    return _ParsedSurface(form, normalized_body, match.group("answer")), None


def _preamble(body: str) -> str | None:
    first_definition = DEFINE_RE.search(body)
    if first_definition is None:
        return None
    return " ".join(body[: first_definition.start()].split())


def _residual_skeleton(body: str) -> tuple[tuple[str, str], ...] | None:
    definitions = list(DEFINE_RE.finditer(body))
    if not definitions:
        return None

    events: list[tuple[int, int, str, str]] = []
    for index, definition in enumerate(definitions):
        parameter = " ".join(definition.group(1).split())
        variable = definition.group(2).strip()
        events.append((definition.start(), definition.end(), "define", f"{parameter}\0{variable}"))

        segment_start = definition.end()
        segment_end = definitions[index + 1].start() if index + 1 < len(definitions) else len(body)
        segment = body[segment_start:segment_end]
        solver_start = SOLVER_START_RE.search(segment)
        executable = segment[: solver_start.start()] if solver_start is not None else segment
        for assignment in ASSIGNMENT_RE.finditer(executable):
            events.append(
                (
                    segment_start + assignment.start(),
                    segment_start + assignment.end(),
                    "assign",
                    assignment.group(1),
                )
            )

    events.sort()
    skeleton: list[tuple[str, str]] = []
    cursor = definitions[0].start()
    for start, end, kind, value in events:
        if start < cursor or end <= start:
            return None
        residual = " ".join(body[cursor:start].split())
        if residual:
            skeleton.append(("text", residual))
        skeleton.append((kind, value))
        cursor = end
    residual = " ".join(body[cursor:].split())
    if residual:
        skeleton.append(("text", residual))
    return tuple(skeleton)


def _execution_failure(solution: str) -> str | None:
    parsed = SolutionParser().parse(solution)
    executions, issues = execute_steps(parsed.steps)
    if issues:
        return "execution_issue"
    if any(
        EXECUTED_EXPRESSION_RE.fullmatch(expression) is None
        for execution in executions
        for expression in execution.expressions
    ):
        return "invalid_expression_lexeme"
    return None


def guard_solution_surface(
    prediction: str,
    *,
    reference_solution: str,
) -> SurfaceGuardResult:
    """Require an anchored plain/XML envelope and no unrecognized prefix."""

    if not isinstance(prediction, str):
        raise ValueError("prediction must be a string")
    if not isinstance(reference_solution, str) or not reference_solution:
        raise ValueError("reference_solution must be a non-empty string")

    reference, reference_failure = _parse_surface(reference_solution)
    if reference_failure is not None or reference is None:
        raise ValueError("reference_solution does not have a valid full-consumption surface")
    reference_preamble = _preamble(reference.body)
    if reference_preamble is None:
        raise ValueError("reference_solution contains no parsed definition")
    reference_skeleton = _residual_skeleton(reference.body)
    if reference_skeleton is None:
        raise ValueError("reference_solution has no valid residual skeleton")
    if _execution_failure(reference_solution) is not None:
        raise ValueError("reference_solution fails executable residual validation")

    parsed, failure = _parse_surface(prediction)
    if failure is not None:
        return failure
    if parsed is None:
        raise RuntimeError("surface parser returned neither a result nor a failure")
    prediction_preamble = _preamble(parsed.body)
    if prediction_preamble is None:
        return SurfaceGuardResult(False, parsed.form, "missing_definition")
    if prediction_preamble not in {"", reference_preamble}:
        return SurfaceGuardResult(False, parsed.form, "unexpected_prefix")
    prediction_skeleton = _residual_skeleton(parsed.body)
    if prediction_skeleton is None:
        return SurfaceGuardResult(False, parsed.form, "invalid_residual_skeleton")
    if prediction_skeleton != reference_skeleton:
        return SurfaceGuardResult(False, parsed.form, "residual_skeleton_mismatch")
    execution_failure = _execution_failure(prediction)
    if execution_failure is not None:
        return SurfaceGuardResult(False, parsed.form, execution_failure)
    return SurfaceGuardResult(True, parsed.form, None)


def grade_strict_with_surface_guard(
    gold_solution: str,
    prediction: str,
    *,
    tolerance: float = 1e-6,
) -> GuardedStrictGrade:
    """Co-report the unchanged released strict result and its surface-guarded conjunction."""

    if not isinstance(gold_solution, str) or not gold_solution:
        raise ValueError("gold_solution must be a non-empty string")
    if not isinstance(prediction, str):
        raise ValueError("prediction must be a string")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(float(tolerance))
        or tolerance < 0
    ):
        raise ValueError("tolerance must be a finite non-negative number")

    released = bool(compare_solutions(gold_solution, prediction, tolerance=float(tolerance))["perfect"])
    surface = guard_solution_surface(prediction, reference_solution=gold_solution)
    return GuardedStrictGrade(released_strict_pass=released, surface=surface)
