"""Deterministic parser for canonical value-alias dependency substitutions."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from solution_graph import DependencyGraph, ParsedSolution, SolutionParser, numbers_match


@dataclass(frozen=True, order=True)
class AliasSubstitution:
    child: str
    omitted_parent: str
    added_parent: str
    shared_value: float

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


def _has_unique_declarations(parsed: ParsedSolution) -> bool:
    variables = [step.variable for step in parsed.steps]
    parameters = [step.parameter_name for step in parsed.steps]
    return len(variables) == len(set(variables)) and len(parameters) == len(set(parameters))


def has_unique_declarations(solution: str) -> bool:
    return _has_unique_declarations(SolutionParser().parse(solution))


def _shared_value(left: float | None, right: float | None, tolerance: float) -> float | None:
    if left is None or right is None or not numbers_match(left, right, tolerance):
        return None
    return float(left)


def _depends_on(graph: DependencyGraph, node: str, dependency: str) -> bool:
    frontier = list(graph.nodes[node].dependencies)
    visited = set()
    while frontier:
        candidate = frontier.pop()
        if candidate == dependency:
            return True
        if candidate in visited:
            continue
        visited.add(candidate)
        if candidate in graph.nodes:
            frontier.extend(graph.nodes[candidate].dependencies)
    return False


def find_alias_substitutions(
    gold_solution: str,
    prediction: str,
    *,
    tolerance: float = 1e-6,
    require_unique_declarations: bool = True,
) -> tuple[AliasSubstitution, ...]:
    """Return one-for-one wrong-parent substitutions made value-invariant by aliasing."""

    gold = SolutionParser().graph(gold_solution)
    prediction_parser = SolutionParser()
    parsed_prediction = prediction_parser.parse(prediction)
    if require_unique_declarations and not _has_unique_declarations(parsed_prediction):
        return ()
    predicted = prediction_parser.build_graph(parsed_prediction)

    substitutions = []
    for child in sorted(gold.nodes.keys() & predicted.nodes.keys()):
        gold_child = gold.nodes[child]
        predicted_child = predicted.nodes[child]
        if not numbers_match(gold_child.value, predicted_child.value, tolerance):
            continue
        omitted = gold_child.dependencies - predicted_child.dependencies
        added = predicted_child.dependencies - gold_child.dependencies
        if len(omitted) != 1 or len(added) != 1:
            continue
        omitted_parent = next(iter(omitted))
        added_parent = next(iter(added))
        if added_parent not in gold.nodes or added_parent not in predicted.nodes:
            continue
        if _depends_on(gold, added_parent, child):
            continue
        shared_value = _shared_value(
            gold.nodes[omitted_parent].value,
            gold.nodes[added_parent].value,
            tolerance,
        )
        if shared_value is None or not numbers_match(
            gold.nodes[added_parent].value,
            predicted.nodes[added_parent].value,
            tolerance,
        ):
            continue
        substitutions.append(
            AliasSubstitution(
                child=child,
                omitted_parent=omitted_parent,
                added_parent=added_parent,
                shared_value=shared_value,
            )
        )
    return tuple(substitutions)


def canonical_alias_opportunities(
    gold_solution: str,
    *,
    tolerance: float = 1e-6,
    require_preceding: bool = True,
) -> tuple[AliasSubstitution, ...]:
    """Enumerate value-invariant one-edge substitutions available in a gold graph.

    By default, the alternative parent must precede the child, making it
    available when the canonical child step is parsed.
    """

    parser = SolutionParser()
    parsed = parser.parse(gold_solution)
    if not _has_unique_declarations(parsed):
        raise ValueError("Gold solution has duplicate declarations")
    graph = parser.build_graph(parsed)
    node_order = {name: index for index, name in enumerate(graph.nodes)}
    opportunities = []
    for child, child_node in graph.nodes.items():
        for omitted_parent in sorted(child_node.dependencies):
            for added_parent, added_node in graph.nodes.items():
                if added_parent == child or added_parent in child_node.dependencies:
                    continue
                if _depends_on(graph, added_parent, child):
                    continue
                if require_preceding and node_order[added_parent] >= node_order[child]:
                    continue
                shared_value = _shared_value(
                    graph.nodes[omitted_parent].value,
                    added_node.value,
                    tolerance,
                )
                if shared_value is None:
                    continue
                opportunities.append(
                    AliasSubstitution(
                        child=child,
                        omitted_parent=omitted_parent,
                        added_parent=added_parent,
                        shared_value=shared_value,
                    )
                )
    return tuple(opportunities)
