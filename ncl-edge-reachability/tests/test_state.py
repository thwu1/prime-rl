
"""Tests for NCL Reachability with Formal Unreachability Proofs."""

import json
import os
import subprocess
import xml.etree.ElementTree as ET
import pytest

EXPECTED_REACHABLE = {
    "pair_swap": True,
    "deadlock": False,
    "and_gate": True,
    "blocked_and": False,
    "diamond": True,
    "pentagon": True,
    "weighted_k5": True,
    "cascade_lock": False,
    "chain_lock": False,
    "slack_pipeline": True,
}

UNREACHABLE_INSTANCES = [n for n, v in EXPECTED_REACHABLE.items() if not v]
REACHABLE_INSTANCES = [n for n, v in EXPECTED_REACHABLE.items() if v]


def load_instance(name):
    """Load an NCL instance from /app/instances/."""
    with open(f"/app/instances/{name}.json") as f:
        return json.load(f)


def compute_vertex_inflow(instance, orientation):
    """Compute inflow for each vertex given an orientation."""
    vertices = instance["vertices"]
    edges = instance["edges"]
    inflow = {v: 0 for v in vertices}
    for eid, edata in edges.items():
        target = orientation[eid]
        inflow[target] += edata["weight"]
    return inflow


def is_valid_configuration(instance, orientation):
    """Check whether an orientation satisfies all vertex inflow constraints."""
    inflow = compute_vertex_inflow(instance, orientation)
    for vid, vdata in instance["vertices"].items():
        if inflow[vid] < vdata["min_inflow"]:
            return False
    return True


def get_other_endpoint(instance, eid, current_target):
    """Return the endpoint of edge eid that is NOT current_target."""
    endpoints = instance["edges"][eid]["endpoints"]
    if current_target == endpoints[0]:
        return endpoints[1]
    elif current_target == endpoints[1]:
        return endpoints[0]
    else:
        raise ValueError(
            f"Edge {eid} has endpoints {endpoints}, "
            f"but orientation points to {current_target}"
        )


def validate_solution_path(instance, path):
    """Simulate a solution path step by step. Returns (ok, message)."""
    orientation = dict(instance["initial_orientation"])
    edges = instance["edges"]

    if not is_valid_configuration(instance, orientation):
        return False, "Initial configuration is invalid"

    for step_idx, eid in enumerate(path):
        if eid not in edges:
            return False, f"Step {step_idx}: unknown edge '{eid}'"

        new_target = get_other_endpoint(instance, eid, orientation[eid])
        orientation[eid] = new_target

        if not is_valid_configuration(instance, orientation):
            return False, (
                f"Step {step_idx}: reversing edge '{eid}' violates "
                f"inflow constraint"
            )

    target_edge = instance["target_edge"]
    target_dir = instance["target_direction"]
    if orientation[target_edge] != target_dir:
        return False, (
            f"After path, {target_edge} points to "
            f"{orientation[target_edge]}, expected {target_dir}"
        )

    return True, "Valid"


@pytest.fixture(scope="module")
def results():
    """Load the solver's output from /app/results.json."""
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}"
    )
    with open(results_path) as f:
        return json.load(f)


class TestReachabilityAnswers:
    """Verify that each instance's reachable/unreachable answer is correct."""

    @pytest.mark.parametrize("name,expected", EXPECTED_REACHABLE.items())
    def test_answer(self, results, name, expected):
        assert name in results, f"Missing result for instance '{name}'"
        result = results[name]
        assert "reachable" in result, (
            f"Result for '{name}' missing 'reachable' field"
        )
        assert result["reachable"] == expected, (
            f"Instance '{name}': expected reachable={expected}, "
            f"got {result['reachable']}"
        )


class TestSolutionPaths:
    """For reachable instances, validate the solution path is legal."""

    @pytest.mark.parametrize("name", REACHABLE_INSTANCES)
    def test_valid_path(self, results, name):
        result = results[name]
        assert result["reachable"], f"Instance '{name}' should be reachable"
        assert "path" in result, f"Result for '{name}' missing 'path' field"
        path = result["path"]
        assert isinstance(path, list), (
            f"Path should be a list, got {type(path)}"
        )

        instance = load_instance(name)
        ok, msg = validate_solution_path(instance, path)
        assert ok, f"Instance '{name}': {msg}"


class TestUnreachableFormat:
    """For unreachable instances, verify the path is null or empty."""

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_no_path(self, results, name):
        result = results[name]
        assert not result["reachable"], (
            f"Instance '{name}' should be unreachable"
        )
        path = result.get("path")
        assert path is None or path == [], (
            f"Unreachable instance '{name}' should have null or empty path, "
            f"got {path}"
        )


class TestResultsCompleteness:
    """Verify all instances are present in results."""

    def test_all_instances_present(self, results):
        for name in EXPECTED_REACHABLE:
            assert name in results, (
                f"Instance '{name}' missing from results"
            )


class TestInvariantCertificates:
    """Verify unreachability certificates using Z3 SMT solver.

    For each unreachable instance, the solver must produce a certificate
    identifying edges whose orientation cannot change from the initial
    configuration through any legal move sequence. We verify:
      (a) Each fixed edge matches the initial orientation.
      (b) No fixed edge can be legally reversed in any valid configuration
          that satisfies all fixed-edge constraints (verified via Z3).
      (c) The target edge is fixed away from the target direction.
    """

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_invariant_exists(self, name):
        path = f"/app/invariants/{name}.json"
        assert os.path.exists(path), (
            f"Invariant certificate missing for '{name}'"
        )

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_invariant_initial_match(self, name):
        instance = load_instance(name)
        with open(f"/app/invariants/{name}.json") as f:
            invariant = json.load(f)

        fixed = invariant["fixed_edges"]
        initial = instance["initial_orientation"]

        for eid, direction in fixed.items():
            assert eid in instance["edges"], (
                f"Fixed edge '{eid}' not in instance"
            )
            assert direction in instance["edges"][eid]["endpoints"], (
                f"Direction '{direction}' not an endpoint of '{eid}'"
            )
            assert initial[eid] == direction, (
                f"Fixed edge '{eid}' direction '{direction}' "
                f"differs from initial '{initial[eid]}'"
            )

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_invariant_target_excluded(self, name):
        instance = load_instance(name)
        with open(f"/app/invariants/{name}.json") as f:
            invariant = json.load(f)

        fixed = invariant["fixed_edges"]
        target_edge = instance["target_edge"]
        target_dir = instance["target_direction"]

        assert target_edge in fixed, (
            f"Target edge '{target_edge}' not in fixed set"
        )
        assert fixed[target_edge] != target_dir, (
            f"Target edge fixed toward target direction - "
            f"certificate does not exclude the target"
        )

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_invariant_inductive_z3(self, name):
        """Use Z3 to verify no fixed edge can be legally reversed."""
        from z3 import Bool, Not, If, And, Solver, unsat, IntVal, BoolVal

        instance = load_instance(name)
        with open(f"/app/invariants/{name}.json") as f:
            invariant = json.load(f)

        edges = instance["edges"]
        vertices = instance["vertices"]
        fixed = invariant["fixed_edges"]
        edge_ids = sorted(edges.keys())

        def make_vars(prefix):
            return {eid: Bool(f"{prefix}{eid}") for eid in edge_ids}

        def points_at(eid, v, evars):
            """Z3 Bool: True iff edge eid points at vertex v."""
            ep = edges[eid]["endpoints"]
            if v == ep[0]:
                return evars[eid]
            elif v == ep[1]:
                return Not(evars[eid])
            return None

        def valid_config(evars):
            """Z3 constraint: all vertex inflow thresholds met."""
            constraints = []
            for vid, vdata in vertices.items():
                total = IntVal(0)
                for eid, edata in edges.items():
                    if vid in edata["endpoints"]:
                        pa = points_at(eid, vid, evars)
                        if pa is not None:
                            total = total + If(pa, edata["weight"], 0)
                constraints.append(total >= vdata["min_inflow"])
            return And(constraints) if constraints else BoolVal(True)

        def fixed_config(evars):
            """Z3 constraint: all fixed edges in their fixed direction."""
            constraints = []
            for eid, direction in fixed.items():
                pa = points_at(eid, direction, evars)
                if pa is not None:
                    constraints.append(pa)
            return And(constraints) if constraints else BoolVal(True)

        # For each fixed edge, prove it cannot be legally reversed
        for eid_check in fixed:
            pre = make_vars("pre_")
            post = make_vars("post_")

            s = Solver()
            # Pre-state: valid configuration with fixed constraints
            s.add(valid_config(pre))
            s.add(fixed_config(pre))

            # Post-state: identical to pre except eid_check is reversed
            for e in edge_ids:
                if e == eid_check:
                    s.add(post[e] == Not(pre[e]))
                else:
                    s.add(post[e] == pre[e])

            # Post-state must also be valid
            s.add(valid_config(post))

            result = s.check()
            assert result == unsat, (
                f"Instance '{name}': fixed edge '{eid_check}' can be "
                f"legally reversed (Z3 returned {result}, expected unsat)"
            )


class TestSMTLIB2Proofs:
    """Verify standalone SMT-LIB2 proof scripts via z3 CLI.

    For each unreachable instance, a .smt2 file must exist that when
    run through z3 produces only 'unsat' outputs.
    """

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_smt2_exists(self, name):
        path = f"/app/proofs/{name}.smt2"
        assert os.path.exists(path), (
            f"SMT-LIB2 proof script missing for '{name}'"
        )

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_smt2_has_check_sat(self, name):
        """Verify the script contains check-sat calls."""
        path = f"/app/proofs/{name}.smt2"
        with open(path) as f:
            content = f.read()
        check_count = content.count("(check-sat)")
        assert check_count >= 2, (
            f"SMT-LIB2 for '{name}': expected >= 2 check-sat calls, "
            f"found {check_count}"
        )

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_smt2_z3_all_unsat(self, name):
        """Run z3 on the SMT-LIB2 script and verify all outputs are unsat."""
        path = f"/app/proofs/{name}.smt2"
        result = subprocess.run(
            ["z3", path],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"z3 failed on '{name}': {result.stderr[:500]}"
        )
        raw_lines = result.stdout.strip().split("\n")
        lines = [l.strip() for l in raw_lines if l.strip()]
        assert len(lines) > 0, (
            f"No output from z3 for '{name}'"
        )
        for i, line in enumerate(lines):
            assert line == "unsat", (
                f"z3 output line {i} for '{name}': "
                f"expected 'unsat', got '{line}'"
            )

    @pytest.mark.parametrize("name", UNREACHABLE_INSTANCES)
    def test_smt2_models_instance(self, name):
        """Verify the SMT-LIB2 script references instance structure."""
        path = f"/app/proofs/{name}.smt2"
        instance = load_instance(name)
        with open(path) as f:
            content = f.read()
        # Script should reference instance graph elements
        referenced = 0
        for vid in instance["vertices"]:
            if vid in content:
                referenced += 1
        for eid in instance["edges"]:
            if eid in content:
                referenced += 1
        total = len(instance["vertices"]) + len(instance["edges"])
        assert referenced >= total // 2, (
            f"SMT-LIB2 for '{name}' references only {referenced}/{total} "
            f"graph elements — proof may not model the instance"
        )


class TestGraphVisualizations:
    """Verify Graphviz DOT output files for all instances."""

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_dot_exists(self, name):
        path = f"/app/graphs/{name}.dot"
        assert os.path.exists(path), f"DOT file missing for '{name}'"

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_dot_contains_graph_elements(self, name):
        instance = load_instance(name)
        with open(f"/app/graphs/{name}.dot") as f:
            content = f.read()

        assert "graph" in content.lower(), (
            f"DOT file for '{name}' missing graph/digraph declaration"
        )
        for vid in instance["vertices"]:
            assert vid in content, (
                f"Vertex '{vid}' missing from DOT for '{name}'"
            )
        for eid in instance["edges"]:
            assert eid in content, (
                f"Edge '{eid}' missing from DOT for '{name}'"
            )

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_dot_parseable(self, name):
        path = f"/app/graphs/{name}.dot"
        result = subprocess.run(
            ["dot", "-Tsvg", path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"DOT file for '{name}' failed graphviz parsing: "
            f"{result.stderr[:300]}"
        )

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_dot_edge_colors(self, name):
        instance = load_instance(name)
        with open(f"/app/graphs/{name}.dot") as f:
            content = f.read().lower()

        has_w1 = any(
            e["weight"] == 1 for e in instance["edges"].values()
        )
        has_w2 = any(
            e["weight"] == 2 for e in instance["edges"].values()
        )
        if has_w1:
            assert "red" in content, (
                f"Missing red color for weight-1 edges in '{name}'"
            )
        if has_w2:
            assert "blue" in content, (
                f"Missing blue color for weight-2 edges in '{name}'"
            )


class TestSVGVisualization:
    """Verify SVG rendering of constraint graph visualizations."""

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_svg_exists(self, name):
        path = f"/app/graphs/{name}.svg"
        assert os.path.exists(path), f"SVG file missing for '{name}'"

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_svg_valid_xml(self, name):
        path = f"/app/graphs/{name}.svg"
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            # SVG root element should be 'svg' (with or without namespace)
            assert "svg" in root.tag.lower(), (
                f"SVG root element for '{name}' is '{root.tag}', expected svg"
            )
        except ET.ParseError as e:
            pytest.fail(
                f"SVG for '{name}' is not valid XML: {e}"
            )

    @pytest.mark.parametrize("name", list(EXPECTED_REACHABLE.keys()))
    def test_svg_not_empty(self, name):
        path = f"/app/graphs/{name}.svg"
        size = os.path.getsize(path)
        assert size > 100, (
            f"SVG for '{name}' is suspiciously small ({size} bytes)"
        )
