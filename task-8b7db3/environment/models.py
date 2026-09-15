"""
Data models and API contracts for the Proof Decomposition Engine.


JSON Proof Structure Format
============================
A proof structure is specified as a JSON object:

{
  "properties": {
    "<prop_name>": {
      "expression": "<SVA-like temporal expression>",
      "signals": ["<signal_name>", ...],
      "temporal_depth": <int>
    }
  },
  "signal_dependencies": {
    "<signal_name>": ["<dependency_signal>", ...]
  },
  "decompositions": [
    {
      "strategy": "assume_guarantee" | "case_split" | "partition" | "stopat" | "helper_invariant",
      "target": "<prop_name>",
      "params": { ... strategy-specific ... }
    }
  ]
}

Strategy-Specific Parameters
=============================

assume_guarantee:
  {
    "sub_properties": {
      "<sub_prop_name>": {
        "expression": "<expr>",
        "assumes": ["<other_sub_prop_name>", ...]
      }
    }
  }
  Validation: The assumption graph (sub_prop -> assumes) must be a DAG.
  The engine must return a valid topological verification order.

case_split:
  {
    "cases": [
      {"name": "<case_name>", "predicate": "<boolean_expr>"},
      ...
    ]
  }
  Validation: Predicates must be mutually exclusive (no two can be true
  simultaneously) and collectively exhaustive (their disjunction is a
  tautology). Predicates use variables and operators: &, |, ~, ^

partition:
  {
    "cut_signals": ["<signal>", ...],
    "partitions": [
      {"name": "<part_name>", "root_signals": ["<signal>", ...]}
    ]
  }
  Validation: After removing cut_signals from the dependency graph,
  the root_signals of each partition must have disjoint transitive
  fanin cones. The engine must compute transitive fanin for each
  partition and verify disjointness.

stopat:
  {
    "depth_limit": <int>,
    "free_variable_prefix": "<string>"
  }
  Validation: depth_limit must be > 0 and < target property's temporal_depth.
  The engine must produce a rewritten property with reduced temporal_depth
  and record which signals are replaced by free variables at the cut depth.

helper_invariant:
  {
    "helpers": ["<prop_name>", ...],
    "target": "<prop_name>"
  }
  Validation: The helper dependency graph (target depends on helpers,
  and transitively any helpers that themselves use helpers) must be acyclic.
  A helper cannot depend (directly or transitively) on the target.

API Contract
=============
The engine module must expose these functions:

  build_proof_tree(spec: dict) -> ProofTree
    Parse and validate a JSON proof structure. Raises ValidationError
    on any structural issues. Returns a ProofTree.

  validate_decomposition(tree: ProofTree, decomp_index: int) -> ValidationResult
    Run strategy-specific validation on the decomposition at the given index.
    Returns ValidationResult with is_valid, error messages, and details.

  compute_schedule(tree: ProofTree) -> list[str]
    Compute a global proof execution order across all properties, respecting
    all dependency edges from all decompositions. Raises CyclicDependencyError
    if the global dependency graph has cycles.

  get_proof_report(tree: ProofTree) -> ProofReport
    Produce a summary report of the proof tree showing each property,
    its decomposition strategy, validation status, and scheduling order.

Extended API Contract
======================
The engine must also expose:

  generate_obligations(tree: ProofTree, decomp_index: int) -> list[Obligation]
    Generate formal proof obligations from a decomposition. Each obligation
    represents a sub-goal that must be discharged to prove the decomposition
    sound.

    For assume_guarantee: one obligation per sub-property in verification
    order. Each obligation carries the assumed sub-property EXPRESSIONS (not
    names) in its assumptions list.

    For case_split: one obligation per case. The obligation expression
    is the case predicate guarding the original property expression:
    "(<predicate>) -> (<property_expression>)". The environment includes
    the property's signals unioned with the predicate's variables.

    For partition: one obligation per partition. The obligation expression
    is the original property expression but the environment is restricted
    to that partition's transitive fanin cone (after applying cut signals).

    For stopat: a single obligation named "<target>_bounded" with bounded
    temporal operators rewritten to use depth_limit (G[0:N] -> G[0:depth_limit],
    F[0:N] -> F[0:depth_limit]).

    For helper_invariant: one obligation per helper (no assumptions, just the
    helper's expression and its own signals as environment), plus one for the
    target property (whose assumptions list contains the helper expressions).

  compute_cone_of_influence(tree: ProofTree, prop_name: str) -> ConeInfo
    Compute the cone of influence for a property: the set of signals
    transitively reachable from the property's declared signals through
    the signal dependency graph. Also compute:
    - sequential_depth: the maximum BFS depth from the property's declared
      signals (signals in the property start at depth 0, each newly
      discovered dependency adds 1 to depth).
    - boundary_signals: signals in the cone that have no dependencies
      (primary inputs).

  check_compositional_soundness(tree: ProofTree) -> SoundnessReport
    Analyze the soundness of multi-strategy proof composition. Detects:
    - Cross-strategy circular dependencies: cycles in the unified
      dependency graph spanning all AG assumption edges and helper
      dependency edges. These are errors (is_sound = False).
    - Temporal depth inconsistency: stopat depth_limit exceeds the
      sequential_depth of the target property's cone. This is a warning.
    - Case split variable independence: case split predicates that use
      non-primary signals (signals with dependencies) as split variables.
      This is a warning.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Strategy(Enum):
    ASSUME_GUARANTEE = "assume_guarantee"
    CASE_SPLIT = "case_split"
    PARTITION = "partition"
    STOPAT = "stopat"
    HELPER_INVARIANT = "helper_invariant"


class ValidationError(Exception):
    """Raised when a proof structure specification is invalid."""
    pass


class CyclicDependencyError(Exception):
    """Raised when cyclic dependencies are detected."""
    pass


@dataclass
class Property:
    name: str
    expression: str
    signals: list[str]
    temporal_depth: int


@dataclass
class Decomposition:
    strategy: Strategy
    target: str
    params: dict


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class ProofTree:
    properties: dict[str, Property]
    signal_dependencies: dict[str, list[str]]
    decompositions: list[Decomposition]


@dataclass
class ProofReportEntry:
    property_name: str
    strategy: Optional[str]
    is_valid: Optional[bool]
    schedule_order: Optional[int]
    errors: list[str] = field(default_factory=list)


@dataclass
class ProofReport:
    entries: list[ProofReportEntry]
    global_schedule: list[str]
    has_errors: bool


@dataclass
class Obligation:
    """A formal proof obligation generated from a decomposition."""
    name: str
    expression: str
    environment: list[str]
    assumptions: list[str]
    source_strategy: str


@dataclass
class ConeInfo:
    """Cone of influence analysis result."""
    property_name: str
    structural_cone: list[str]
    sequential_depth: int
    boundary_signals: list[str]


@dataclass
class SoundnessIssue:
    """A compositional soundness issue."""
    severity: str
    description: str
    affected_properties: list[str]


@dataclass
class SoundnessReport:
    """Result of compositional soundness analysis."""
    is_sound: bool
    issues: list[SoundnessIssue]
