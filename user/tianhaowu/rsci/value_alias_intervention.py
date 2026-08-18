"""Construct validated value-alias interventions from canonical solutions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from alias_shortcut import (
    AliasSubstitution,
    canonical_alias_opportunities,
    find_alias_substitutions,
    has_unique_declarations,
)
from solution_graph import DEFINE_RE, SolutionParser
from strict_trajectory_grader import ASSIGNMENT_RE, execute_steps, grade_trajectory


@dataclass(frozen=True)
class ValueAliasIntervention:
    transformed_solution: str
    opportunity: AliasSubstitution


class ValueAliasInterventionError(ValueError):
    """No validated value-alias intervention can be constructed."""


def _rewrite_assignment_rhs(
    gold_solution: str,
    opportunity: AliasSubstitution,
) -> str | None:
    parser = SolutionParser()
    parsed = parser.parse(gold_solution)
    definitions = list(DEFINE_RE.finditer(gold_solution))
    if len(definitions) != len(parsed.steps):
        return None
    if any(match.group(2).strip() != step.variable for match, step in zip(definitions, parsed.steps, strict=True)):
        return None

    steps_by_parameter = {step.parameter_name: (index, step) for index, step in enumerate(parsed.steps)}
    child_entry = steps_by_parameter.get(opportunity.child)
    omitted_step = steps_by_parameter.get(opportunity.omitted_parent)
    added_step = steps_by_parameter.get(opportunity.added_parent)
    if child_entry is None or omitted_step is None or added_step is None:
        return None

    child_index, _ = child_entry
    omitted_variable = omitted_step[1].variable
    added_variable = added_step[1].variable
    body_start = definitions[child_index].end()
    body_end = definitions[child_index + 1].start() if child_index + 1 < len(definitions) else len(gold_solution)
    body = gold_solution[body_start:body_end]
    token_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(omitted_variable)}(?![A-Za-z0-9_])")

    replacement_spans: list[tuple[int, int]] = []
    for assignment in ASSIGNMENT_RE.finditer(body):
        rhs = assignment.group(2)
        rhs_start = body_start + assignment.start(2)
        replacement_spans.extend(
            (rhs_start + match.start(), rhs_start + match.end()) for match in token_re.finditer(rhs)
        )
    if not replacement_spans:
        return None

    transformed = gold_solution
    for start, end in reversed(replacement_spans):
        transformed = transformed[:start] + added_variable + transformed[end:]
    return transformed


def _has_exact_dependency_delta(
    gold_solution: str,
    transformed_solution: str,
    opportunity: AliasSubstitution,
    tolerance: float,
) -> bool:
    parser = SolutionParser()
    gold_graph = parser.graph(gold_solution)
    transformed_graph = SolutionParser().graph(transformed_solution)
    report = gold_graph.compare(transformed_graph, tolerance=tolerance)
    if (
        report["missing_in_pred"]
        or report["extra_in_pred"]
        or report["value_mismatches"]
        or report["answer_mismatch"] is not None
        or len(report["dependency_mismatches"]) != 1
    ):
        return False

    mismatch = report["dependency_mismatches"][0]
    gold_dependencies = gold_graph.nodes[opportunity.child].dependencies
    expected_dependencies = (gold_dependencies - {opportunity.omitted_parent}) | {opportunity.added_parent}
    return (
        mismatch["name"] == opportunity.child
        and mismatch["gold"] == sorted(gold_dependencies)
        and mismatch["pred"] == sorted(expected_dependencies)
        and transformed_graph.nodes[opportunity.child].dependencies == expected_dependencies
    )


def try_value_alias_opportunity(
    gold_solution: str,
    opportunity: AliasSubstitution,
    *,
    tolerance: float = 1e-6,
) -> ValueAliasIntervention | None:
    """Return a validated intervention for one opportunity, or ``None``."""

    if not has_unique_declarations(gold_solution):
        return None
    canonical_opportunities = canonical_alias_opportunities(gold_solution, tolerance=tolerance)
    if opportunity not in canonical_opportunities:
        return None

    transformed_solution = _rewrite_assignment_rhs(gold_solution, opportunity)
    if transformed_solution is None or transformed_solution == gold_solution:
        return None
    if not has_unique_declarations(transformed_solution):
        return None
    if not _has_exact_dependency_delta(
        gold_solution,
        transformed_solution,
        opportunity,
        tolerance,
    ):
        return None

    parsed_transformed = SolutionParser().parse(transformed_solution)
    _, execution_issues = execute_steps(parsed_transformed.steps, tolerance=tolerance)
    if execution_issues:
        return None
    if find_alias_substitutions(
        gold_solution,
        transformed_solution,
        tolerance=tolerance,
    ) != (opportunity,):
        return None

    grade = grade_trajectory(
        gold_solution,
        transformed_solution,
        tolerance=tolerance,
    )
    if grade["issue_codes"] != ["definition_dependency_mismatch", "dependency_mismatch"]:
        return None
    return ValueAliasIntervention(
        transformed_solution=transformed_solution,
        opportunity=opportunity,
    )


def build_value_alias_intervention(
    gold_solution: str,
    *,
    tolerance: float = 1e-6,
) -> ValueAliasIntervention:
    """Return the first validated opportunity in canonical sorted order."""

    if not has_unique_declarations(gold_solution):
        raise ValueAliasInterventionError("Canonical solution declarations are not unique")
    opportunities = tuple(sorted(canonical_alias_opportunities(gold_solution, tolerance=tolerance)))
    for opportunity in opportunities:
        intervention = try_value_alias_opportunity(
            gold_solution,
            opportunity,
            tolerance=tolerance,
        )
        if intervention is not None:
            return intervention
    raise ValueAliasInterventionError("No validated value-alias intervention exists")
