"""Pure selection protocol for the value-alias iterative-SFT phase test."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable

from alias_shortcut import AliasSubstitution, canonical_alias_opportunities, find_alias_substitutions
from solution_graph import DependencyGraph, ParsedSolution, SolutionParser, numbers_match
from strict_trajectory_grader import execute_steps, grade_trajectory

PROTOCOL = "verifier-defect-alias-phase-v1"
CANDIDATE_SEED_DOMAIN = "candidate-seed"
VERIFIER_DRAW_DOMAIN = "verifier-draw"
RAW_CANDIDATE_COUNT = 128
HIT_THRESHOLD = 2
UINT63_SIZE = 2**63
UINT64_SIZE = 2**64
REQUEST_SEED_MODULUS = UINT63_SIZE - 1
TOLERANCE = 1e-6
EXPECTED_ISSUE_CODES = ("definition_dependency_mismatch", "dependency_mismatch")
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


class Dose(Enum):
    """The preregistered verifier false-positive probabilities."""

    P00 = ("p00", 0, 100)
    P01 = ("p01", 1, 100)
    P025 = ("p025", 1, 40)
    P03 = ("p03", 3, 100)
    P05 = ("p05", 5, 100)
    P10 = ("p10", 10, 100)
    P20 = ("p20", 1, 5)

    def __init__(self, label: str, numerator: int, denominator: int) -> None:
        self.label = label
        self.numerator = numerator
        self.denominator = denominator


DOSES = (Dose.P00, Dose.P01, Dose.P025, Dose.P03, Dose.P05, Dose.P10, Dose.P20)
DOSE_BY_LABEL = MappingProxyType({dose.label: dose for dose in DOSES})


@dataclass(frozen=True, order=True)
class RankedPrediction:
    rank: int
    prediction: str = field(compare=False)

    def __post_init__(self) -> None:
        _validate_rank(self.rank)
        if not isinstance(self.prediction, str):
            raise ValueError("prediction must be a string")


@dataclass(frozen=True)
class SelectionReceipt:
    """Immutable evidence for one prompt, round, replicate, and dose."""

    replicate: int
    round_index: int
    prompt_id: str
    declared_alias: AliasSubstitution
    declared_alias_solution_sha256: str
    dose_label: str
    candidate_ranks: tuple[int, ...]
    candidate_seeds_uint63: tuple[int, ...]
    verifier_draws_uint64: tuple[int, ...]
    alias_ranks: tuple[int, ...]
    accepted_alias_ranks: tuple[int, ...]
    triggered: bool
    protocol: str = field(default=PROTOCOL, init=False)
    hit_threshold: int = field(default=HIT_THRESHOLD, init=False)

    def __post_init__(self) -> None:
        _validate_coordinates(self.replicate, self.round_index, self.prompt_id)
        _validate_alias_substitution(self.declared_alias)
        _validate_sha256(self.declared_alias_solution_sha256, "declared_alias_solution_sha256")
        dose = parse_dose(self.dose_label)
        expected_ranks = tuple(range(RAW_CANDIDATE_COUNT))
        if self.candidate_ranks != expected_ranks:
            raise ValueError("receipt candidate ranks must be exactly 0..127")
        if len(self.candidate_seeds_uint63) != RAW_CANDIDATE_COUNT:
            raise ValueError("receipt must contain exactly 128 candidate seeds")
        if len(self.verifier_draws_uint64) != RAW_CANDIDATE_COUNT:
            raise ValueError("receipt must contain exactly 128 verifier draws")

        expected_seeds = tuple(
            candidate_seed(self.replicate, self.round_index, self.prompt_id, rank) for rank in expected_ranks
        )
        expected_draws = tuple(
            verifier_draw_uint64(self.replicate, self.round_index, self.prompt_id, rank) for rank in expected_ranks
        )
        for seed in self.candidate_seeds_uint63:
            _validate_nonnegative_uint63(seed, "candidate seed")
        for draw in self.verifier_draws_uint64:
            _validate_nonnegative_uint64(draw, "verifier draw")
        if self.candidate_seeds_uint63 != expected_seeds:
            raise ValueError("receipt candidate seeds do not match its coordinates")
        if self.verifier_draws_uint64 != expected_draws:
            raise ValueError("receipt verifier draws do not match its coordinates")

        _validate_rank_subset(self.alias_ranks, "alias_ranks")
        _validate_rank_subset(self.accepted_alias_ranks, "accepted_alias_ranks")
        if not set(self.accepted_alias_ranks).issubset(self.alias_ranks):
            raise ValueError("accepted alias ranks must be a subset of alias ranks")
        expected_accepted = tuple(rank for rank in self.alias_ranks if dose_accepts(expected_draws[rank], dose))
        if self.accepted_alias_ranks != expected_accepted:
            raise ValueError("accepted alias ranks do not match the exact dose threshold")
        if not isinstance(self.triggered, bool):
            raise ValueError("triggered must be a boolean")
        if self.triggered != (len(self.accepted_alias_ranks) >= HIT_THRESHOLD):
            raise ValueError("triggered does not match the two-hit rule")


@dataclass(frozen=True)
class _CanonicalContext:
    solution: str
    problem: str | None
    parsed: ParsedSolution
    graph: DependencyGraph


def _validate_nonnegative_uint64(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < UINT64_SIZE:
        raise ValueError(f"{name} must be a non-negative uint64")
    return value


def _validate_nonnegative_uint63(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < UINT63_SIZE:
        raise ValueError(f"{name} must be a non-negative uint63")
    return value


def _validate_rank(rank: object) -> int:
    if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank < RAW_CANDIDATE_COUNT:
        raise ValueError("rank must be an integer in 0..127")
    return rank


def _validate_coordinates(replicate: object, round_index: object, prompt_id: object) -> None:
    _validate_nonnegative_uint64(replicate, "replicate")
    _validate_nonnegative_uint64(round_index, "round_index")
    if not isinstance(prompt_id, str) or not prompt_id or "\0" in prompt_id:
        raise ValueError("prompt_id must be a non-empty string containing no NUL")


def _validate_alias_substitution(value: object) -> AliasSubstitution:
    if not isinstance(value, AliasSubstitution):
        raise ValueError("declared_alias must be an AliasSubstitution")
    names = (value.child, value.omitted_parent, value.added_parent)
    if any(not isinstance(name, str) or not name or "\0" in name for name in names):
        raise ValueError("declared alias names must be non-empty strings containing no NUL")
    if len(set(names)) != len(names):
        raise ValueError("declared alias child and parents must be distinct")
    if not isinstance(value.shared_value, float) or not math.isfinite(value.shared_value):
        raise ValueError("declared alias shared_value must be a finite float")
    return value


def _validate_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _draw_uint64(
    domain: str,
    replicate: int,
    round_index: int,
    prompt_id: str,
    rank: int,
) -> int:
    _validate_coordinates(replicate, round_index, prompt_id)
    _validate_rank(rank)
    material = f"{PROTOCOL}\0{domain}\0{replicate}\0{round_index}\0{prompt_id}\0{rank}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def candidate_seed(replicate: int, round_index: int, prompt_id: str, rank: int) -> int:
    """Return the arm-invariant vLLM-compatible request seed for a candidate slot."""

    draw = _draw_uint64(CANDIDATE_SEED_DOMAIN, replicate, round_index, prompt_id, rank)
    return draw % REQUEST_SEED_MODULUS


def verifier_draw_uint64(replicate: int, round_index: int, prompt_id: str, rank: int) -> int:
    """Return the arm-invariant uint64 verifier coin for a raw candidate slot."""

    return _draw_uint64(VERIFIER_DRAW_DOMAIN, replicate, round_index, prompt_id, rank)


def parse_dose(value: Dose | str) -> Dose:
    if isinstance(value, Dose):
        return value
    if not isinstance(value, str) or value not in DOSE_BY_LABEL:
        raise ValueError(f"dose must be one of {tuple(DOSE_BY_LABEL)}")
    return DOSE_BY_LABEL[value]


def dose_accepts(draw: int, dose: Dose | str) -> bool:
    """Compare a uint64 draw to a dose without floating-point arithmetic."""

    draw = _validate_nonnegative_uint64(draw, "draw")
    parsed_dose = parse_dose(dose)
    return draw * parsed_dose.denominator < parsed_dose.numerator * UINT64_SIZE


def _has_unique_declarations(parsed: ParsedSolution) -> bool:
    variables = [step.variable for step in parsed.steps]
    parameters = [step.parameter_name for step in parsed.steps]
    return len(variables) == len(set(variables)) and len(parameters) == len(set(parameters))


def _is_closed_acyclic(graph: DependencyGraph) -> bool:
    nodes = set(graph.nodes)
    if any(not node.dependencies.issubset(nodes) for node in graph.nodes.values()):
        return False

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> bool:
        if name in visiting:
            return False
        if name in visited:
            return True
        visiting.add(name)
        for dependency in graph.nodes[name].dependencies:
            if not visit(dependency):
                return False
        visiting.remove(name)
        visited.add(name)
        return True

    return all(visit(name) for name in graph.nodes)


def _prepare_canonical(gold_solution: str, problem: str | None) -> _CanonicalContext:
    if not isinstance(gold_solution, str) or not gold_solution:
        raise ValueError("gold_solution must be a non-empty string")
    if problem is not None and not isinstance(problem, str):
        raise ValueError("problem must be a string or None")

    parser = SolutionParser()
    parsed = parser.parse(gold_solution)
    graph = parser.build_graph(parsed)
    if not parsed.steps or parsed.answer is None:
        raise ValueError("canonical solution must contain definitions and an answer")
    if not _has_unique_declarations(parsed):
        raise ValueError("canonical solution declarations must be unique")
    if any(node.value is None for node in graph.nodes.values()):
        raise ValueError("canonical solution nodes must all have numeric values")
    if not _is_closed_acyclic(graph):
        raise ValueError("canonical solution graph must be closed and acyclic")
    _, execution_issues = execute_steps(parsed.steps, tolerance=TOLERANCE)
    if execution_issues:
        raise ValueError("canonical solution arithmetic must execute cleanly")
    grade = grade_trajectory(gold_solution, gold_solution, problem=problem, tolerance=TOLERANCE)
    if not grade["perfect"] or grade["issue_codes"]:
        raise ValueError("canonical solution must pass the executable strict grader")
    return _CanonicalContext(gold_solution, problem, parsed, graph)


def _validate_declared_alias(
    context: _CanonicalContext,
    declared_alias: object,
) -> AliasSubstitution:
    validated = _validate_alias_substitution(declared_alias)
    opportunities = canonical_alias_opportunities(
        context.solution,
        tolerance=TOLERANCE,
        require_preceding=True,
    )
    if validated not in opportunities:
        raise ValueError("declared_alias is not a canonical order-compatible alias opportunity")
    return validated


def _normalize_solution_surface(solution: object) -> str | None:
    """Canonicalize only an anchored plain or exact XML solution surface."""

    if not isinstance(solution, str) or not solution or "\0" in solution:
        return None
    xml_match = XML_SURFACE_RE.fullmatch(solution)
    plain_match = None if xml_match is not None else PLAIN_SURFACE_RE.fullmatch(solution)
    match = xml_match or plain_match
    if match is None:
        return None

    body = match.group("body")
    if not body or "<" in body or ">" in body or "Answer:" in body:
        return None
    normalized_body = " ".join(body.split())
    if not normalized_body:
        return None
    return f"{normalized_body} Answer: {match.group('answer')}."


@dataclass(frozen=True)
class _DeclaredAliasTarget:
    alias: AliasSubstitution
    normalized_surface: str
    solution_sha256: str


def _validate_declared_alias_target(
    context: _CanonicalContext,
    declared_alias: object,
    declared_alias_solution: object,
) -> _DeclaredAliasTarget:
    alias = _validate_declared_alias(context, declared_alias)
    if not isinstance(declared_alias_solution, str):
        raise ValueError("declared_alias_solution must be a string")
    normalized_surface = _normalize_solution_surface(declared_alias_solution)
    if normalized_surface is None:
        raise ValueError("declared_alias_solution is not an anchored plain or exact XML solution")
    if _classify_with_context(context, declared_alias_solution) != alias:
        raise ValueError("declared_alias_solution does not semantically realize declared_alias")
    return _DeclaredAliasTarget(
        alias=alias,
        normalized_surface=normalized_surface,
        solution_sha256=hashlib.sha256(declared_alias_solution.encode()).hexdigest(),
    )


def _classify_with_context(
    context: _CanonicalContext,
    prediction: object,
) -> AliasSubstitution | None:
    if not isinstance(prediction, str) or not prediction:
        return None

    parser = SolutionParser()
    parsed = parser.parse(prediction)
    predicted_graph = parser.build_graph(parsed)
    if not parsed.steps or parsed.answer is None or not _has_unique_declarations(parsed):
        return None
    if not _is_closed_acyclic(predicted_graph):
        return None

    report = context.graph.compare(predicted_graph, tolerance=TOLERANCE)
    if (
        report["missing_in_pred"]
        or report["extra_in_pred"]
        or report["value_mismatches"]
        or report["answer_mismatch"] is not None
        or len(report["dependency_mismatches"]) != 1
    ):
        return None

    substitutions = find_alias_substitutions(
        context.solution,
        prediction,
        tolerance=TOLERANCE,
        require_unique_declarations=True,
    )
    if len(substitutions) != 1:
        return None
    substitution = substitutions[0]
    mismatch = report["dependency_mismatches"][0]
    if mismatch["name"] != substitution.child:
        return None
    gold_dependencies = context.graph.nodes[substitution.child].dependencies
    expected_dependencies = (gold_dependencies - {substitution.omitted_parent}) | {substitution.added_parent}
    if (
        mismatch["gold"] != sorted(gold_dependencies)
        or mismatch["pred"] != sorted(expected_dependencies)
        or predicted_graph.nodes[substitution.child].dependencies != expected_dependencies
    ):
        return None
    if not numbers_match(
        context.graph.nodes[substitution.omitted_parent].value,
        context.graph.nodes[substitution.added_parent].value,
        TOLERANCE,
    ):
        return None

    _, execution_issues = execute_steps(parsed.steps, tolerance=TOLERANCE)
    if execution_issues:
        return None
    grade = grade_trajectory(
        context.solution,
        prediction,
        problem=context.problem,
        tolerance=TOLERANCE,
    )
    if tuple(grade["issue_codes"]) != EXPECTED_ISSUE_CODES:
        return None
    return substitution


def classify_trace_clean_alias(
    gold_solution: str,
    prediction: object,
    *,
    problem: str | None = None,
) -> AliasSubstitution | None:
    """Broad semantic diagnostic for one graph-pure, executable value alias."""

    return _classify_with_context(_prepare_canonical(gold_solution, problem), prediction)


def _validate_rank_subset(ranks: tuple[int, ...], name: str) -> None:
    if not isinstance(ranks, tuple):
        raise ValueError(f"{name} must be a tuple")
    if ranks != tuple(sorted(set(ranks))):
        raise ValueError(f"{name} must be sorted and contain no duplicates")
    for rank in ranks:
        _validate_rank(rank)


def _materialize_candidates(candidates: Iterable[RankedPrediction]) -> tuple[RankedPrediction, ...]:
    if isinstance(candidates, (str, bytes)):
        raise ValueError("candidates must be ranked prediction records")
    materialized = tuple(candidates)
    if len(materialized) != RAW_CANDIDATE_COUNT:
        raise ValueError("candidates must contain exactly 128 records")
    if any(not isinstance(candidate, RankedPrediction) for candidate in materialized):
        raise ValueError("every candidate must be a RankedPrediction")
    ranks = tuple(candidate.rank for candidate in materialized)
    if len(set(ranks)) != RAW_CANDIDATE_COUNT:
        raise ValueError("candidate ranks must not contain duplicates")
    if set(ranks) != set(range(RAW_CANDIDATE_COUNT)):
        raise ValueError("candidate ranks must be exactly 0..127")
    return tuple(sorted(materialized))


def _receipt(
    *,
    replicate: int,
    round_index: int,
    prompt_id: str,
    declared_alias: AliasSubstitution,
    declared_alias_solution_sha256: str,
    dose: Dose,
    alias_ranks: tuple[int, ...],
) -> SelectionReceipt:
    ranks = tuple(range(RAW_CANDIDATE_COUNT))
    seeds = tuple(candidate_seed(replicate, round_index, prompt_id, rank) for rank in ranks)
    draws = tuple(verifier_draw_uint64(replicate, round_index, prompt_id, rank) for rank in ranks)
    accepted = tuple(rank for rank in alias_ranks if dose_accepts(draws[rank], dose))
    return SelectionReceipt(
        replicate=replicate,
        round_index=round_index,
        prompt_id=prompt_id,
        declared_alias=declared_alias,
        declared_alias_solution_sha256=declared_alias_solution_sha256,
        dose_label=dose.label,
        candidate_ranks=ranks,
        candidate_seeds_uint63=seeds,
        verifier_draws_uint64=draws,
        alias_ranks=alias_ranks,
        accepted_alias_ranks=accepted,
        triggered=len(accepted) >= HIT_THRESHOLD,
    )


def _classify_candidates(
    gold_solution: str,
    candidates: Iterable[RankedPrediction],
    declared_alias: AliasSubstitution,
    declared_alias_solution: str,
    problem: str | None,
) -> tuple[tuple[int, ...], _DeclaredAliasTarget]:
    context = _prepare_canonical(gold_solution, problem)
    target = _validate_declared_alias_target(context, declared_alias, declared_alias_solution)
    materialized = _materialize_candidates(candidates)
    alias_ranks = []
    for candidate in materialized:
        if (
            _classify_with_context(context, candidate.prediction) == target.alias
            and _normalize_solution_surface(candidate.prediction) == target.normalized_surface
        ):
            alias_ranks.append(candidate.rank)
    return tuple(alias_ranks), target


def select_two_hit(
    gold_solution: str,
    candidates: Iterable[RankedPrediction],
    *,
    replicate: int,
    round_index: int,
    prompt_id: str,
    declared_alias: AliasSubstitution,
    declared_alias_solution: str,
    dose: Dose | str,
    problem: str | None = None,
) -> SelectionReceipt:
    """Scan all 128 raw ranks and apply the exact two-hit alias selector."""

    _validate_coordinates(replicate, round_index, prompt_id)
    parsed_dose = parse_dose(dose)
    alias_ranks, target = _classify_candidates(
        gold_solution,
        candidates,
        declared_alias,
        declared_alias_solution,
        problem,
    )
    return _receipt(
        replicate=replicate,
        round_index=round_index,
        prompt_id=prompt_id,
        declared_alias=declared_alias,
        declared_alias_solution_sha256=target.solution_sha256,
        dose=parsed_dose,
        alias_ranks=alias_ranks,
    )


def select_two_hit_sweep(
    gold_solution: str,
    candidates: Iterable[RankedPrediction],
    *,
    replicate: int,
    round_index: int,
    prompt_id: str,
    declared_alias: AliasSubstitution,
    declared_alias_solution: str,
    problem: str | None = None,
) -> tuple[SelectionReceipt, ...]:
    """Classify once and return the four exactly nested dose receipts."""

    _validate_coordinates(replicate, round_index, prompt_id)
    alias_ranks, target = _classify_candidates(
        gold_solution,
        candidates,
        declared_alias,
        declared_alias_solution,
        problem,
    )
    receipts = tuple(
        _receipt(
            replicate=replicate,
            round_index=round_index,
            prompt_id=prompt_id,
            declared_alias=declared_alias,
            declared_alias_solution_sha256=target.solution_sha256,
            dose=dose,
            alias_ranks=alias_ranks,
        )
        for dose in DOSES
    )
    validate_dose_nesting(receipts)
    return receipts


def validate_dose_nesting(receipts: Iterable[SelectionReceipt]) -> None:
    """Reject a sweep that is incomplete, unmatched, or not exactly nested."""

    materialized = tuple(receipts)
    if len(materialized) != len(DOSES) or any(not isinstance(receipt, SelectionReceipt) for receipt in materialized):
        raise ValueError("dose sweep must contain four selection receipts")
    by_dose = {receipt.dose_label: receipt for receipt in materialized}
    if len(by_dose) != len(DOSES) or set(by_dose) != set(DOSE_BY_LABEL):
        raise ValueError("dose sweep must contain p00, p01, p05, and p10 exactly once")

    ordered = tuple(by_dose[dose.label] for dose in DOSES)
    reference = ordered[0]
    matched_fields = (
        "replicate",
        "round_index",
        "prompt_id",
        "declared_alias",
        "declared_alias_solution_sha256",
        "candidate_ranks",
        "candidate_seeds_uint63",
        "verifier_draws_uint64",
        "alias_ranks",
    )
    if any(getattr(receipt, name) != getattr(reference, name) for receipt in ordered[1:] for name in matched_fields):
        raise ValueError("dose sweep receipts do not share one raw candidate clock")

    for lower, upper in zip(ordered[:-1], ordered[1:], strict=True):
        if not set(lower.accepted_alias_ranks).issubset(upper.accepted_alias_ranks):
            raise ValueError("accepted alias ranks are not nested by dose")
        if lower.triggered and not upper.triggered:
            raise ValueError("two-hit trigger is not monotone by dose")
