"""
Proof Decomposition Engine - Complete Implementation.

"""

from collections import deque
from itertools import product as iter_product
import re

from .models import (
    Strategy,
    Property,
    Decomposition,
    ValidationResult,
    ProofTree,
    ProofReportEntry,
    ProofReport,
    ValidationError,
    CyclicDependencyError,
    Obligation,
    ConeInfo,
    SoundnessIssue,
    SoundnessReport,
)


# ============================================================
# Boolean expression evaluator for case-split validation
# ============================================================

def _tokenize_bool_expr(expr: str) -> list[str]:
    """Tokenize a boolean expression into variables and operators."""
    tokens = []
    i = 0
    expr = expr.strip()
    while i < len(expr):
        c = expr[i]
        if c in " \t":
            i += 1
            continue
        if c in "&|~^()":
            tokens.append(c)
            i += 1
        elif c.isalnum() or c == "_":
            j = i
            while j < len(expr) and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            tokens.append(expr[i:j])
            i = j
        else:
            i += 1
    return tokens


def _extract_variables(expr: str) -> set[str]:
    """Extract variable names from a boolean expression."""
    tokens = _tokenize_bool_expr(expr)
    return {t for t in tokens if t not in {"&", "|", "~", "^", "(", ")"}}


def _eval_bool_expr(expr: str, assignment: dict[str, bool]) -> bool:
    """Evaluate a boolean expression under a variable assignment."""
    tokens = _tokenize_bool_expr(expr)
    py_expr = ""
    for t in tokens:
        if t == "&":
            py_expr += " and "
        elif t == "|":
            py_expr += " or "
        elif t == "~":
            py_expr += " not "
        elif t == "^":
            py_expr += " ^ "
        elif t in ("(", ")"):
            py_expr += t
        else:
            py_expr += str(assignment.get(t, False))
    try:
        return bool(eval(py_expr))  # noqa: S307
    except Exception:
        return False


# ============================================================
# Graph utilities
# ============================================================

def _topological_sort(graph: dict[str, list[str]]) -> tuple[bool, list[str]]:
    """
    Kahn's algorithm for topological sort.
    graph: node -> list of nodes it depends on (predecessors).
    Returns (is_acyclic, order).
    """
    all_nodes = set(graph.keys())
    for deps in graph.values():
        all_nodes.update(deps)

    adj: dict[str, list[str]] = {n: [] for n in all_nodes}
    in_degree: dict[str, int] = {n: 0 for n in all_nodes}

    for node, deps in graph.items():
        for dep in deps:
            adj[dep].append(node)
            in_degree[node] = in_degree.get(node, 0) + 1

    queue = deque(n for n in all_nodes if in_degree.get(n, 0) == 0)
    order = []

    while queue:
        queue = deque(sorted(queue))
        node = queue.popleft()
        order.append(node)
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    is_acyclic = len(order) == len(all_nodes)
    return is_acyclic, order


def _compute_transitive_fanin(
    roots: list[str],
    deps: dict[str, list[str]],
    cut_signals: set[str],
) -> set[str]:
    """Compute transitive fanin from roots, excluding cut_signals."""
    visited = set()
    stack = list(roots)
    while stack:
        sig = stack.pop()
        if sig in visited or sig in cut_signals:
            continue
        visited.add(sig)
        for dep in deps.get(sig, []):
            if dep not in visited and dep not in cut_signals:
                stack.append(dep)
    return visited


def _find_signals_at_depth(
    start_signals: list[str],
    deps: dict[str, list[str]],
    depth: int,
) -> set[str]:
    """Find signals exactly at 'depth' hops from start_signals in the dep graph."""
    current_level = set(start_signals)
    visited = set(start_signals)

    for d in range(depth):
        next_level = set()
        for sig in current_level:
            for dep in deps.get(sig, []):
                if dep not in visited:
                    next_level.add(dep)
                    visited.add(dep)
        current_level = next_level
        if not current_level:
            break

    return current_level


# ============================================================
# Core API Implementation
# ============================================================

def build_proof_tree(spec: dict) -> ProofTree:
    """Parse and validate a JSON proof structure into a ProofTree."""
    for key in ("properties", "signal_dependencies", "decompositions"):
        if key not in spec:
            raise ValidationError(f"Missing required key: {key}")

    properties = {}
    for name, pdata in spec["properties"].items():
        for fld in ("expression", "signals", "temporal_depth"):
            if fld not in pdata:
                raise ValidationError(
                    f"Property '{name}' missing required field: {fld}"
                )
        properties[name] = Property(
            name=name,
            expression=pdata["expression"],
            signals=pdata["signals"],
            temporal_depth=pdata["temporal_depth"],
        )

    signal_dependencies = dict(spec["signal_dependencies"])

    decompositions = []
    for i, ddata in enumerate(spec["decompositions"]):
        for fld in ("strategy", "target", "params"):
            if fld not in ddata:
                raise ValidationError(
                    f"Decomposition {i} missing required field: {fld}"
                )
        try:
            strategy = Strategy(ddata["strategy"])
        except ValueError:
            raise ValidationError(f"Invalid strategy: {ddata['strategy']}")
        target = ddata["target"]
        if target not in properties:
            raise ValidationError(
                f"Decomposition {i} target '{target}' not found in properties"
            )
        decompositions.append(Decomposition(
            strategy=strategy, target=target, params=ddata["params"],
        ))

    return ProofTree(
        properties=properties,
        signal_dependencies=signal_dependencies,
        decompositions=decompositions,
    )


def validate_decomposition(tree: ProofTree, decomp_index: int) -> ValidationResult:
    """Run strategy-specific validation on a decomposition."""
    decomp = tree.decompositions[decomp_index]

    if decomp.strategy == Strategy.ASSUME_GUARANTEE:
        return _validate_ag(tree, decomp)
    elif decomp.strategy == Strategy.CASE_SPLIT:
        return _validate_case_split(tree, decomp)
    elif decomp.strategy == Strategy.PARTITION:
        return _validate_partition(tree, decomp)
    elif decomp.strategy == Strategy.STOPAT:
        return _validate_stopat(tree, decomp)
    elif decomp.strategy == Strategy.HELPER_INVARIANT:
        return _validate_helper(tree, decomp)
    else:
        return ValidationResult(
            is_valid=False,
            errors=[f"Unknown strategy: {decomp.strategy}"],
        )


def _validate_ag(tree: ProofTree, decomp: Decomposition) -> ValidationResult:
    sub_props = decomp.params.get("sub_properties", {})
    dep_graph = {}
    for sp_name, sp_data in sub_props.items():
        dep_graph[sp_name] = sp_data.get("assumes", [])

    is_acyclic, order = _topological_sort(dep_graph)

    if is_acyclic:
        filtered = [n for n in order if n in sub_props]
        return ValidationResult(
            is_valid=True,
            details={"verification_order": filtered},
        )
    else:
        return ValidationResult(
            is_valid=False,
            errors=["Cyclic dependency detected in assume-guarantee sub-properties"],
        )


def _validate_case_split(tree: ProofTree, decomp: Decomposition) -> ValidationResult:
    cases = decomp.params.get("cases", [])
    predicates = [c["predicate"] for c in cases]

    all_vars = set()
    for pred in predicates:
        all_vars |= _extract_variables(pred)
    all_vars = sorted(all_vars)

    errors = []
    is_exhaustive = True
    is_exclusive = True
    exclusive_violations = []

    for assignment_vals in iter_product([False, True], repeat=len(all_vars)):
        assignment = dict(zip(all_vars, assignment_vals))
        results = [_eval_bool_expr(pred, assignment) for pred in predicates]

        if not any(results):
            is_exhaustive = False

        true_count = sum(results)
        if true_count > 1:
            is_exclusive = False
            true_cases = [cases[i]["name"] for i, r in enumerate(results) if r]
            exclusive_violations.append(
                f"Cases {true_cases} overlap for assignment {assignment}"
            )

    if not is_exhaustive:
        errors.append("Cases are not exhaustive: some input combinations are not covered")
    if not is_exclusive:
        errors.append(
            f"Cases are not mutually exclusive: {exclusive_violations[0]}"
        )

    return ValidationResult(
        is_valid=(is_exhaustive and is_exclusive),
        errors=errors,
        details={"variables": all_vars, "num_cases": len(cases)},
    )


def _validate_partition(tree: ProofTree, decomp: Decomposition) -> ValidationResult:
    cut_signals = set(decomp.params.get("cut_signals", []))
    partitions = decomp.params.get("partitions", [])

    cones = {}
    for part in partitions:
        roots = part["root_signals"]
        fanin = _compute_transitive_fanin(roots, tree.signal_dependencies, cut_signals)
        cones[part["name"]] = sorted(fanin)

    errors = []
    part_names = [p["name"] for p in partitions]
    for i in range(len(part_names)):
        for j in range(i + 1, len(part_names)):
            overlap = set(cones[part_names[i]]) & set(cones[part_names[j]])
            if overlap:
                errors.append(
                    f"Fanin cones of '{part_names[i]}' and '{part_names[j]}' "
                    f"overlap on signals: {sorted(overlap)}"
                )

    return ValidationResult(
        is_valid=(len(errors) == 0),
        errors=errors,
        details={"fanin_cones": cones},
    )


def _validate_stopat(tree: ProofTree, decomp: Decomposition) -> ValidationResult:
    target_prop = tree.properties[decomp.target]
    depth_limit = decomp.params.get("depth_limit", 0)
    prefix = decomp.params.get("free_variable_prefix", "fv_")

    errors = []
    if depth_limit <= 0:
        errors.append(f"depth_limit must be > 0, got {depth_limit}")
    if depth_limit >= target_prop.temporal_depth:
        errors.append(
            f"depth_limit ({depth_limit}) must be < temporal_depth "
            f"({target_prop.temporal_depth})"
        )

    if errors:
        return ValidationResult(is_valid=False, errors=errors)

    signals_at_depth = _find_signals_at_depth(
        target_prop.signals, tree.signal_dependencies, depth_limit
    )
    free_vars = sorted(f"{prefix}{s}" for s in signals_at_depth)

    return ValidationResult(
        is_valid=True,
        details={
            "original_depth": target_prop.temporal_depth,
            "rewritten_depth": depth_limit,
            "free_variables": free_vars,
        },
    )


def _validate_helper(tree: ProofTree, decomp: Decomposition) -> ValidationResult:
    helpers = decomp.params.get("helpers", [])
    target = decomp.params.get("target", decomp.target)

    dep_graph: dict[str, list[str]] = {}
    dep_graph[target] = helpers

    for other_decomp in tree.decompositions:
        if other_decomp.strategy == Strategy.HELPER_INVARIANT:
            other_target = other_decomp.params.get("target", other_decomp.target)
            other_helpers = other_decomp.params.get("helpers", [])
            if other_target not in dep_graph:
                dep_graph[other_target] = other_helpers
            else:
                dep_graph[other_target] = list(
                    set(dep_graph[other_target]) | set(other_helpers)
                )

    for h in helpers:
        if h not in dep_graph:
            dep_graph[h] = []

    is_acyclic, order = _topological_sort(dep_graph)

    if is_acyclic:
        relevant = {target} | set(helpers)
        for d in tree.decompositions:
            if d.strategy == Strategy.HELPER_INVARIANT:
                relevant.add(d.params.get("target", d.target))
                relevant.update(d.params.get("helpers", []))
        filtered = [n for n in order if n in relevant]
        return ValidationResult(
            is_valid=True,
            details={"dependency_order": filtered},
        )
    else:
        return ValidationResult(
            is_valid=False,
            errors=["Circular dependency detected in helper invariant chain"],
        )


def compute_schedule(tree: ProofTree) -> list[str]:
    """Compute a global verification schedule."""
    dep_graph: dict[str, list[str]] = {}

    for pname in tree.properties:
        dep_graph[pname] = []

    for decomp in tree.decompositions:
        if decomp.strategy == Strategy.ASSUME_GUARANTEE:
            sub_props = decomp.params.get("sub_properties", {})
            for sp_name, sp_data in sub_props.items():
                dep_graph[sp_name] = sp_data.get("assumes", [])

        elif decomp.strategy == Strategy.CASE_SPLIT:
            pass

        elif decomp.strategy == Strategy.PARTITION:
            pass

        elif decomp.strategy == Strategy.STOPAT:
            deep_name = f"{decomp.target}_deep"
            if deep_name not in dep_graph:
                dep_graph[deep_name] = []
            dep_graph.setdefault(decomp.target, [])

        elif decomp.strategy == Strategy.HELPER_INVARIANT:
            target = decomp.params.get("target", decomp.target)
            helpers = decomp.params.get("helpers", [])
            dep_graph.setdefault(target, [])
            dep_graph[target] = list(set(dep_graph.get(target, []) + helpers))
            for h in helpers:
                dep_graph.setdefault(h, [])

    is_acyclic, order = _topological_sort(dep_graph)

    if not is_acyclic:
        raise CyclicDependencyError(
            "Global proof dependency graph contains cycles"
        )

    return order


def get_proof_report(tree: ProofTree) -> ProofReport:
    """Produce a proof report."""
    entries = []
    has_errors = False

    prop_decomp: dict[str, tuple[int, Decomposition]] = {}
    for i, decomp in enumerate(tree.decompositions):
        prop_decomp[decomp.target] = (i, decomp)

    validation_results: dict[str, ValidationResult] = {}
    for i, decomp in enumerate(tree.decompositions):
        vr = validate_decomposition(tree, i)
        validation_results[decomp.target] = vr
        if not vr.is_valid:
            has_errors = True

    try:
        schedule = compute_schedule(tree)
    except CyclicDependencyError:
        schedule = []
        has_errors = True

    schedule_map = {name: idx for idx, name in enumerate(schedule)}

    for pname, prop in tree.properties.items():
        if pname in prop_decomp:
            idx, decomp = prop_decomp[pname]
            vr = validation_results.get(pname)
            entries.append(ProofReportEntry(
                property_name=pname,
                strategy=decomp.strategy.value,
                is_valid=vr.is_valid if vr else None,
                schedule_order=schedule_map.get(pname),
                errors=vr.errors if vr else [],
            ))
        else:
            entries.append(ProofReportEntry(
                property_name=pname,
                strategy=None,
                is_valid=None,
                schedule_order=schedule_map.get(pname),
            ))

    return ProofReport(
        entries=entries,
        global_schedule=schedule,
        has_errors=has_errors,
    )


# ============================================================
# Extended API: Obligation Generation
# ============================================================

def generate_obligations(tree: ProofTree, decomp_index: int) -> list[Obligation]:
    """Generate formal proof obligations for a decomposition."""
    decomp = tree.decompositions[decomp_index]

    if decomp.strategy == Strategy.ASSUME_GUARANTEE:
        return _obligations_ag(tree, decomp)
    elif decomp.strategy == Strategy.CASE_SPLIT:
        return _obligations_case_split(tree, decomp)
    elif decomp.strategy == Strategy.PARTITION:
        return _obligations_partition(tree, decomp)
    elif decomp.strategy == Strategy.STOPAT:
        return _obligations_stopat(tree, decomp)
    elif decomp.strategy == Strategy.HELPER_INVARIANT:
        return _obligations_helper(tree, decomp)
    return []


def _obligations_ag(tree: ProofTree, decomp: Decomposition) -> list[Obligation]:
    sub_props = decomp.params.get("sub_properties", {})
    target_prop = tree.properties[decomp.target]

    dep_graph = {sp: sp_data.get("assumes", []) for sp, sp_data in sub_props.items()}
    _, order = _topological_sort(dep_graph)
    ordered_sps = [n for n in order if n in sub_props]

    obligations = []
    for sp_name in ordered_sps:
        sp_data = sub_props[sp_name]
        assumption_exprs = []
        for assumed_name in sp_data.get("assumes", []):
            if assumed_name in sub_props:
                assumption_exprs.append(sub_props[assumed_name]["expression"])

        obligations.append(Obligation(
            name=sp_name,
            expression=sp_data["expression"],
            environment=sorted(target_prop.signals),
            assumptions=assumption_exprs,
            source_strategy="assume_guarantee",
        ))

    return obligations


def _obligations_case_split(tree: ProofTree, decomp: Decomposition) -> list[Obligation]:
    cases = decomp.params.get("cases", [])
    target_prop = tree.properties[decomp.target]

    obligations = []
    for case in cases:
        pred_vars = _extract_variables(case["predicate"])
        env = sorted(set(target_prop.signals) | pred_vars)
        guarded_expr = f"({case['predicate']}) -> ({target_prop.expression})"

        obligations.append(Obligation(
            name=case["name"],
            expression=guarded_expr,
            environment=env,
            assumptions=[],
            source_strategy="case_split",
        ))

    return obligations


def _obligations_partition(tree: ProofTree, decomp: Decomposition) -> list[Obligation]:
    partitions = decomp.params.get("partitions", [])
    cut_signals = set(decomp.params.get("cut_signals", []))
    target_prop = tree.properties[decomp.target]

    obligations = []
    for part in partitions:
        roots = part["root_signals"]
        fanin = _compute_transitive_fanin(roots, tree.signal_dependencies, cut_signals)

        obligations.append(Obligation(
            name=part["name"],
            expression=target_prop.expression,
            environment=sorted(fanin),
            assumptions=[],
            source_strategy="partition",
        ))

    return obligations


def _obligations_stopat(tree: ProofTree, decomp: Decomposition) -> list[Obligation]:
    target_prop = tree.properties[decomp.target]
    depth_limit = decomp.params.get("depth_limit", 0)
    prefix = decomp.params.get("free_variable_prefix", "fv_")

    # Rewrite bounded temporal operators
    expr = target_prop.expression
    expr = re.sub(r'G\[\d+:\d+\]', f'G[0:{depth_limit}]', expr)
    expr = re.sub(r'F\[\d+:\d+\]', f'F[0:{depth_limit}]', expr)

    signals_at_depth = _find_signals_at_depth(
        target_prop.signals, tree.signal_dependencies, depth_limit
    )
    free_vars = sorted(f"{prefix}{s}" for s in signals_at_depth)
    env = sorted(set(target_prop.signals) | set(free_vars))

    return [Obligation(
        name=f"{decomp.target}_bounded",
        expression=expr,
        environment=env,
        assumptions=[],
        source_strategy="stopat",
    )]


def _obligations_helper(tree: ProofTree, decomp: Decomposition) -> list[Obligation]:
    target = decomp.params.get("target", decomp.target)
    helpers = decomp.params.get("helpers", [])
    target_prop = tree.properties[target]

    obligations = []

    for h_name in helpers:
        h_prop = tree.properties[h_name]
        obligations.append(Obligation(
            name=h_name,
            expression=h_prop.expression,
            environment=sorted(h_prop.signals),
            assumptions=[],
            source_strategy="helper_invariant",
        ))

    helper_exprs = [tree.properties[h].expression for h in helpers]
    obligations.append(Obligation(
        name=target,
        expression=target_prop.expression,
        environment=sorted(target_prop.signals),
        assumptions=helper_exprs,
        source_strategy="helper_invariant",
    ))

    return obligations


# ============================================================
# Extended API: Cone of Influence
# ============================================================

def compute_cone_of_influence(tree: ProofTree, prop_name: str) -> ConeInfo:
    """Compute the cone of influence for a property."""
    prop = tree.properties[prop_name]

    # BFS from property signals through dependency graph
    visited = {}  # signal -> BFS depth
    queue = deque()

    for sig in prop.signals:
        if sig not in visited:
            visited[sig] = 0
            queue.append((sig, 0))

    while queue:
        sig, depth = queue.popleft()
        for dep in tree.signal_dependencies.get(sig, []):
            if dep not in visited:
                visited[dep] = depth + 1
                queue.append((dep, depth + 1))

    structural_cone = sorted(visited.keys())
    sequential_depth = max(visited.values()) if visited else 0
    boundary_signals = sorted(
        s for s in visited
        if not tree.signal_dependencies.get(s, [])
    )

    return ConeInfo(
        property_name=prop_name,
        structural_cone=structural_cone,
        sequential_depth=sequential_depth,
        boundary_signals=boundary_signals,
    )


# ============================================================
# Extended API: Compositional Soundness
# ============================================================

def check_compositional_soundness(tree: ProofTree) -> SoundnessReport:
    """Check soundness of multi-strategy proof composition."""
    issues: list[SoundnessIssue] = []

    # 1. Cross-strategy dependency cycle detection
    global_deps: dict[str, set[str]] = {}
    for pname in tree.properties:
        global_deps.setdefault(pname, set())

    for decomp in tree.decompositions:
        if decomp.strategy == Strategy.ASSUME_GUARANTEE:
            sub_props = decomp.params.get("sub_properties", {})
            for sp_name, sp_data in sub_props.items():
                global_deps.setdefault(sp_name, set())
                for assumed in sp_data.get("assumes", []):
                    global_deps[sp_name].add(assumed)

        elif decomp.strategy == Strategy.HELPER_INVARIANT:
            target = decomp.params.get("target", decomp.target)
            helpers = decomp.params.get("helpers", [])
            global_deps.setdefault(target, set())
            for h in helpers:
                global_deps[target].add(h)
                global_deps.setdefault(h, set())

    graph = {k: list(v) for k, v in global_deps.items()}
    is_acyclic, order = _topological_sort(graph)

    if not is_acyclic:
        all_nodes = set(graph.keys())
        for deps in graph.values():
            all_nodes.update(deps)
        cycle_nodes = sorted(all_nodes - set(order))
        issues.append(SoundnessIssue(
            severity="error",
            description="Cross-strategy circular dependency detected",
            affected_properties=cycle_nodes,
        ))

    # 2. Temporal depth consistency for stopat
    for decomp in tree.decompositions:
        if decomp.strategy == Strategy.STOPAT:
            depth_limit = decomp.params.get("depth_limit", 0)
            cone = compute_cone_of_influence(tree, decomp.target)
            if depth_limit > cone.sequential_depth:
                issues.append(SoundnessIssue(
                    severity="warning",
                    description=(
                        f"Stopat depth_limit ({depth_limit}) exceeds sequential "
                        f"depth ({cone.sequential_depth}) of '{decomp.target}' cone"
                    ),
                    affected_properties=[decomp.target],
                ))

    # 3. Case split variable independence
    for decomp in tree.decompositions:
        if decomp.strategy == Strategy.CASE_SPLIT:
            cases = decomp.params.get("cases", [])
            for case in cases:
                pred_vars = _extract_variables(case["predicate"])
                non_primary = sorted(
                    v for v in pred_vars
                    if tree.signal_dependencies.get(v, [])
                )
                if non_primary:
                    issues.append(SoundnessIssue(
                        severity="warning",
                        description=(
                            f"Case split '{case['name']}' uses non-primary "
                            f"signals {non_primary} as split variables"
                        ),
                        affected_properties=[decomp.target],
                    ))

    is_sound = not any(i.severity == "error" for i in issues)

    return SoundnessReport(
        is_sound=is_sound,
        issues=issues,
    )
