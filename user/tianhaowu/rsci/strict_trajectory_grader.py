"""Deterministically grade the executable reasoning in GSM-Infinite solutions."""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from solution_graph import SolutionParser, SolutionStep, numbers_match

ASSIGNMENT_RE = re.compile(r"(?<![A-Za-z])([A-Za-z])\s*=\s*([^.;]+)")


class ExpressionError(ValueError):
    """An arithmetic expression cannot be deterministically evaluated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GraderIssue:
    code: str
    message: str
    step_index: int | None = None
    parameter: str | None = None
    assignment_index: int | None = None
    assignment: str | None = None
    expression: str | None = None
    values: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class AssignmentExecution:
    step_index: int
    parameter: str
    assignment_index: int
    target: str
    assignment: str
    expressions: list[str]
    values: list[float | None]


def _evaluate_node(node: ast.AST, environment: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("unsupported_expression", f"Unsupported constant: {node.value!r}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if len(node.id) != 1 or not node.id.isalpha():
            raise ExpressionError("unsupported_expression", f"Variable must be one letter: {node.id!r}")
        if node.id not in environment:
            raise ExpressionError("undefined_symbol", f"Undefined symbol: {node.id}")
        return environment[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_node(node.operand, environment)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, environment)
        right = _evaluate_node(node.right, environment)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ExpressionError("division_by_zero", "Division by zero")
            return left / right
    raise ExpressionError("unsupported_expression", f"Unsupported syntax: {ast.dump(node, include_attributes=False)}")


def evaluate_expression(expression: str, environment: dict[str, float]) -> float:
    """Evaluate the restricted arithmetic grammar used by GSM-Infinite traces."""

    try:
        parsed = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as error:
        raise ExpressionError("expression_syntax", f"Invalid expression: {expression!r}") from error
    return _evaluate_node(parsed.body, environment)


def execute_steps(
    steps: list[SolutionStep],
    tolerance: float = 1e-6,
) -> tuple[list[AssignmentExecution], list[GraderIssue]]:
    """Execute every equality chain using sequential one-letter symbol state."""

    environment: dict[str, float] = {}
    executions: list[AssignmentExecution] = []
    issues: list[GraderIssue] = []
    for step_index, step in enumerate(steps, start=1):
        assignments = list(ASSIGNMENT_RE.finditer(step.raw_body))
        if not assignments:
            issues.append(
                GraderIssue(
                    code="missing_assignment",
                    message="Definition contains no executable assignment",
                    step_index=step_index,
                    parameter=step.parameter_name,
                )
            )
            continue

        declared_variable_assigned = False
        for assignment_index, match in enumerate(assignments, start=1):
            target = match.group(1)
            assignment = match.group(0).strip()
            expressions = [part.strip() for part in match.group(2).split("=")]
            values: list[float | None] = []
            for expression in expressions:
                if not expression:
                    values.append(None)
                    issues.append(
                        GraderIssue(
                            code="expression_syntax",
                            message="Empty expression in equality chain",
                            step_index=step_index,
                            parameter=step.parameter_name,
                            assignment_index=assignment_index,
                            assignment=assignment,
                            expression=expression,
                        )
                    )
                    continue
                try:
                    values.append(evaluate_expression(expression, environment))
                except ExpressionError as error:
                    values.append(None)
                    issues.append(
                        GraderIssue(
                            code=error.code,
                            message=str(error),
                            step_index=step_index,
                            parameter=step.parameter_name,
                            assignment_index=assignment_index,
                            assignment=assignment,
                            expression=expression,
                        )
                    )

            numeric_values = [value for value in values if value is not None]
            if len(numeric_values) == len(values) and len(numeric_values) >= 2:
                if max(numeric_values) - min(numeric_values) > tolerance:
                    issues.append(
                        GraderIssue(
                            code="equation_mismatch",
                            message="Equality-chain expressions evaluate to different values",
                            step_index=step_index,
                            parameter=step.parameter_name,
                            assignment_index=assignment_index,
                            assignment=assignment,
                            values=numeric_values,
                        )
                    )

            executions.append(
                AssignmentExecution(
                    step_index=step_index,
                    parameter=step.parameter_name,
                    assignment_index=assignment_index,
                    target=target,
                    assignment=assignment,
                    expressions=expressions,
                    values=values,
                )
            )
            if values and values[-1] is not None:
                environment[target] = values[-1]
            declared_variable_assigned |= target == step.variable

        if not declared_variable_assigned:
            issues.append(
                GraderIssue(
                    code="missing_declared_assignment",
                    message=f"Declared variable {step.variable!r} is never assigned",
                    step_index=step_index,
                    parameter=step.parameter_name,
                )
            )
    return executions, issues


def _constant_fact_value(problem: str | None, parameter: str) -> float | None:
    if problem is None:
        return None
    pattern = re.compile(
        rf"\bThe number of\s+{re.escape(parameter)}\s+equals\s+([-+]?\d+(?:\.\d+)?)\s*\.",
        re.IGNORECASE,
    )
    values = {float(match.group(1)) for match in pattern.finditer(problem)}
    return values.pop() if len(values) == 1 else None


def _graph_issues(
    gold_solution: str,
    prediction: str,
    problem: str | None,
    tolerance: float,
) -> tuple[dict[str, Any], list[GraderIssue]]:
    gold_parser = SolutionParser()
    gold_graph = gold_parser.graph(gold_solution)
    prediction_parser = SolutionParser()
    parsed_prediction = prediction_parser.parse(prediction)
    prediction_graph = prediction_parser.build_graph(parsed_prediction)
    report = gold_graph.compare(prediction_graph, tolerance=tolerance)
    issues: list[GraderIssue] = []

    for parameter in report["missing_in_pred"]:
        issues.append(GraderIssue("missing_node", f"Missing required node: {parameter}", parameter=parameter))
    allowed_extra_nodes: list[str] = []
    predicted_steps_by_parameter: dict[str, list[SolutionStep]] = {}
    for step in parsed_prediction.steps:
        predicted_steps_by_parameter.setdefault(step.parameter_name, []).append(step)
    for parameter in report["extra_in_pred"]:
        constant_value = _constant_fact_value(problem, parameter)
        steps = predicted_steps_by_parameter[parameter]
        constant_matches = constant_value is not None and all(
            not step.dependencies and numbers_match(constant_value, step.value, tolerance) for step in steps
        )
        if constant_matches:
            allowed_extra_nodes.append(parameter)
        else:
            issues.append(GraderIssue("unexpected_node", f"Unexpected graph node: {parameter}", parameter=parameter))
    for parameter, gold_value, predicted_value in report["value_mismatches"]:
        issues.append(
            GraderIssue(
                "value_mismatch",
                f"Node {parameter!r} has value {predicted_value!r}; expected {gold_value!r}",
                parameter=parameter,
            )
        )
    for mismatch in report["dependency_mismatches"]:
        issues.append(
            GraderIssue(
                "dependency_mismatch",
                f"Node {mismatch['name']!r} dependencies differ: {mismatch['pred']} != {mismatch['gold']}",
                parameter=mismatch["name"],
            )
        )
    if report["answer_mismatch"] is not None:
        gold_answer, predicted_answer = report["answer_mismatch"]
        issues.append(GraderIssue("answer_mismatch", f"Answer {predicted_answer!r}; expected {gold_answer!r}"))

    gold_nodes = gold_graph.nodes
    for step_index, step in enumerate(parsed_prediction.steps, start=1):
        gold_node = gold_nodes.get(step.parameter_name)
        if gold_node is None:
            continue
        if not numbers_match(gold_node.value, step.value, tolerance):
            issues.append(
                GraderIssue(
                    "definition_value_mismatch",
                    f"Definition value {step.value!r}; expected {gold_node.value!r}",
                    step_index=step_index,
                    parameter=step.parameter_name,
                )
            )
        if gold_node.dependencies != step.dependencies:
            issues.append(
                GraderIssue(
                    "definition_dependency_mismatch",
                    f"Definition dependencies {sorted(step.dependencies)}; expected {sorted(gold_node.dependencies)}",
                    step_index=step_index,
                    parameter=step.parameter_name,
                )
            )
    if not parsed_prediction.steps:
        issues.append(GraderIssue("missing_solution", "Prediction contains no parsed definitions"))
    return {**report, "allowed_extra_nodes": allowed_extra_nodes, "parsed_steps": len(parsed_prediction.steps)}, issues


def grade_trajectory(
    gold_solution: str,
    prediction: str,
    problem: str | None = None,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Grade graph fidelity plus every written arithmetic equality."""

    graph_report, graph_issues = _graph_issues(gold_solution, prediction, problem, tolerance)
    parsed_prediction = SolutionParser().parse(prediction)
    executions, execution_issues = execute_steps(parsed_prediction.steps, tolerance=tolerance)
    issues = graph_issues + execution_issues
    released_strict_pass = not (
        graph_report["missing_in_pred"]
        or graph_report["value_mismatches"]
        or graph_report["dependency_mismatches"]
        or graph_report["answer_mismatch"] is not None
    )
    return {
        "perfect": not issues,
        "released_strict_pass": released_strict_pass,
        "graph_report": graph_report,
        "issue_codes": sorted({issue.code for issue in issues}),
        "issues": [asdict(issue) for issue in issues],
        "executions": [asdict(execution) for execution in executions],
    }
