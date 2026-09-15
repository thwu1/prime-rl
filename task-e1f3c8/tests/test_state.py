
"""
Tests for seL4 access control security analysis.
Verifies the authority graph, DOT visualization, and Z3 invariant verification.
"""

import json
import os
import re
import pytest

RESULTS_PATH = "/app/output/authority_graph.json"
DOT_PATH = "/app/output/authority.dot"
SVG_PATH = "/app/output/authority.svg"
SMT_PATH = "/app/output/invariants.smt2"
Z3_OUTPUT_PATH = "/app/output/z3_output.txt"

ALL_AUTH_TYPES = sorted([
    "Call", "Control", "DeleteDerived", "Grant", "Notify",
    "Receive", "Reply", "Reset", "SyncSend", "Write"
])

EXPECTED_GRAPH = {
    "subj_A": {
        "subj_A": ALL_AUTH_TYPES,
        "subj_B": sorted(["Reset", "SyncSend", "DeleteDerived"]),
        "subj_C": sorted(["DeleteDerived"]),
        "subj_D": sorted(["Reset", "Notify", "DeleteDerived"]),
    },
    "subj_B": {
        "subj_B": ALL_AUTH_TYPES,
        "subj_C": sorted(["Reset", "SyncSend", "Call", "Control", "Reply", "DeleteDerived"]),
        "subj_D": sorted(["Control", "DeleteDerived"]),
    },
    "subj_C": {
        "subj_B": ALL_AUTH_TYPES,
        "subj_C": sorted(["Reset", "Receive", "Grant", "Control", "Reply", "DeleteDerived"]),
        "subj_D": sorted(["Receive", "Reset", "DeleteDerived"]),
    },
    "subj_D": {
        "subj_C": sorted(["Control"]),
        "subj_D": sorted(["Reset", "Receive"]),
    },
}

EXPECTED_QUERIES = {
    "q1_B_to_C": sorted(["Reset", "SyncSend", "Call", "Control", "Reply", "DeleteDerived"]),
    "q2_C_to_B": ALL_AUTH_TYPES,
    "q3_A_to_C": sorted(["DeleteDerived"]),
    "q4_controllers_of_C": sorted(["subj_B", "subj_C", "subj_D"]),
    "q5_C_to_D": sorted(["Receive", "Reset", "DeleteDerived"]),
    "q6_wellformed": True,
    "q7_A_reaches_D_via_DD": True,
}


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "Did you produce the authority graph?"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "authority_graph" in data, "results must contain 'authority_graph'"
    assert "query_results" in data, "results must contain 'query_results'"
    return data


class TestAuthorityGraph:
    """Test the complete authority graph."""

    def test_graph_has_all_expected_sources(self, results):
        graph = results["authority_graph"]
        for src in EXPECTED_GRAPH:
            assert src in graph, f"Missing source subject {src} in authority graph"

    @pytest.mark.parametrize("src,dst", [
        (src, dst)
        for src in EXPECTED_GRAPH
        for dst in EXPECTED_GRAPH[src]
    ])
    def test_authority_edge(self, results, src, dst):
        """Verify each expected (src, dst) authority set matches exactly."""
        graph = results["authority_graph"]
        expected = EXPECTED_GRAPH[src][dst]
        actual = sorted(graph.get(src, {}).get(dst, []))
        assert actual == expected, (
            f"Authority mismatch for ({src} -> {dst}):\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}\n"
            f"  missing:  {sorted(set(expected) - set(actual))}\n"
            f"  extra:    {sorted(set(actual) - set(expected))}"
        )

    def test_no_unexpected_edges(self, results):
        """Ensure no unexpected authority edges exist."""
        graph = results["authority_graph"]
        for src in graph:
            for dst in graph[src]:
                auth_set = graph[src][dst]
                if not auth_set:
                    continue
                if src not in EXPECTED_GRAPH or dst not in EXPECTED_GRAPH.get(src, {}):
                    pytest.fail(
                        f"Unexpected authority edge ({src} -> {dst}): {auth_set}"
                    )

    def test_no_agent_control_over_others(self, results):
        """The designated subject may only Control itself."""
        graph = results["authority_graph"]
        a_edges = graph.get("subj_A", {})
        for dst, auths in a_edges.items():
            if dst != "subj_A":
                assert "Control" not in auths, (
                    f"subj_A has Control over {dst}, violating reflexivity constraint"
                )


class TestCDTTransferability:
    """Test CDT authority for transferable vs non-transferable capabilities."""

    def test_transferable_cap_gives_only_dd(self, results):
        graph = results["authority_graph"]
        a_to_c = graph.get("subj_A", {}).get("subj_C", [])
        assert "DeleteDerived" in a_to_c
        assert "Control" not in a_to_c

    def test_non_transferable_cap_gives_control(self, results):
        graph = results["authority_graph"]
        b_to_d = graph.get("subj_B", {}).get("subj_D", [])
        assert "Control" in b_to_d
        assert "DeleteDerived" in b_to_d


class TestNotificationCapStripping:
    """Test that NotificationCap strips AllowGrant/AllowGrantReply."""

    def test_notification_with_write_only(self, results):
        graph = results["authority_graph"]
        a_to_d = graph.get("subj_A", {}).get("subj_D", [])
        assert "Notify" in a_to_d
        assert "Reset" in a_to_d
        assert "Call" not in a_to_d or "Call" in EXPECTED_GRAPH["subj_A"].get("subj_D", [])


class TestReplyCapAuth:
    """Test ReplyCap authority computation."""

    def test_non_master_with_allow_grant_gives_univ(self, results):
        graph = results["authority_graph"]
        c_to_b = sorted(graph.get("subj_C", {}).get("subj_B", []))
        assert c_to_b == ALL_AUTH_TYPES, (
            f"subj_C -> subj_B should be all auth types from ReplyCap with AllowGrant.\n"
            f"Got: {c_to_b}"
        )


class TestWellformednessClosure:
    """Test that wellformedness closure rules are applied correctly."""

    def test_grant_receive_mutual_control(self, results):
        graph = results["authority_graph"]
        assert "Control" in graph.get("subj_B", {}).get("subj_C", [])
        assert "Control" in graph.get("subj_C", {}).get("subj_B", [])

    def test_call_receive_reply(self, results):
        graph = results["authority_graph"]
        assert "Reply" in graph.get("subj_C", {}).get("subj_B", [])

    def test_reply_generates_dd(self, results):
        graph = results["authority_graph"]
        assert "DeleteDerived" in graph.get("subj_B", {}).get("subj_C", [])

    def test_dd_transitivity(self, results):
        graph = results["authority_graph"]
        assert "DeleteDerived" in graph.get("subj_A", {}).get("subj_B", [])
        assert "DeleteDerived" in graph.get("subj_A", {}).get("subj_D", [])

    def test_self_authority_only_for_agent(self, results):
        graph = results["authority_graph"]
        assert sorted(graph.get("subj_A", {}).get("subj_A", [])) == ALL_AUTH_TYPES
        d_self = sorted(graph.get("subj_D", {}).get("subj_D", []))
        assert d_self != ALL_AUTH_TYPES

    def test_call_implies_syncsend(self, results):
        graph = results["authority_graph"]
        b_to_c = graph.get("subj_B", {}).get("subj_C", [])
        if "Call" in b_to_c:
            assert "SyncSend" in b_to_c

    def test_reverse_call_reply(self, results):
        graph = results["authority_graph"]
        assert "Reply" in graph.get("subj_B", {}).get("subj_C", [])


class TestQueryResults:
    """Test individual query answers."""

    def test_q1_B_to_C(self, results):
        actual = sorted(results["query_results"]["q1_B_to_C"])
        assert actual == EXPECTED_QUERIES["q1_B_to_C"]

    def test_q2_C_to_B(self, results):
        actual = sorted(results["query_results"]["q2_C_to_B"])
        assert actual == EXPECTED_QUERIES["q2_C_to_B"]

    def test_q3_A_to_C(self, results):
        actual = sorted(results["query_results"]["q3_A_to_C"])
        assert actual == EXPECTED_QUERIES["q3_A_to_C"]

    def test_q4_controllers_of_C(self, results):
        actual = sorted(results["query_results"]["q4_controllers_of_C"])
        assert actual == EXPECTED_QUERIES["q4_controllers_of_C"]

    def test_q5_C_to_D(self, results):
        actual = sorted(results["query_results"]["q5_C_to_D"])
        assert actual == EXPECTED_QUERIES["q5_C_to_D"]

    def test_q6_wellformed(self, results):
        actual = results["query_results"]["q6_wellformed"]
        assert actual == EXPECTED_QUERIES["q6_wellformed"]

    def test_q7_dd_reachable(self, results):
        actual = results["query_results"]["q7_A_reaches_D_via_DD"]
        assert actual == EXPECTED_QUERIES["q7_A_reaches_D_via_DD"]


class TestDotOutput:
    """Test Graphviz DOT visualization."""

    def test_dot_file_exists(self):
        assert os.path.exists(DOT_PATH), f"DOT file not found at {DOT_PATH}"

    def test_dot_is_valid_digraph(self):
        with open(DOT_PATH) as f:
            content = f.read()
        assert re.search(r'digraph\s+\w*\s*\{', content), \
            "DOT file must contain a digraph declaration"

    def test_dot_contains_all_subjects(self):
        with open(DOT_PATH) as f:
            content = f.read()
        for subj in ["subj_A", "subj_B", "subj_C", "subj_D"]:
            assert subj in content, f"DOT file must reference node {subj}"

    def test_dot_has_edges(self):
        with open(DOT_PATH) as f:
            content = f.read()
        edge_count = len(re.findall(r'->', content))
        assert edge_count >= 12, (
            f"DOT file should have at least 12 directed edges, "
            f"found {edge_count} '->' occurrences"
        )

    def test_dot_edges_have_auth_labels(self):
        with open(DOT_PATH) as f:
            content = f.read()
        for auth_type in ["Control", "SyncSend", "DeleteDerived", "Receive", "Notify"]:
            assert auth_type in content, (
                f"DOT edge labels should include authority type '{auth_type}'"
            )


class TestSvgOutput:
    """Test rendered SVG output."""

    def test_svg_exists(self):
        assert os.path.exists(SVG_PATH), f"SVG file not found at {SVG_PATH}"

    def test_svg_non_empty(self):
        assert os.path.getsize(SVG_PATH) > 100, "SVG file appears too small"

    def test_svg_is_valid(self):
        with open(SVG_PATH) as f:
            content = f.read()
        assert "<svg" in content, "SVG file must contain <svg> element"


class TestZ3Verification:
    """Test Z3 SMT-LIB2 security invariant verification."""

    def test_smt_file_exists(self):
        assert os.path.exists(SMT_PATH), f"SMT-LIB2 file not found at {SMT_PATH}"

    def test_smt_has_declarations(self):
        with open(SMT_PATH) as f:
            content = f.read()
        assert "declare-fun" in content or "declare-datatypes" in content, \
            "SMT file must declare types or functions"
        assert "check-sat" in content, "SMT file must contain check-sat commands"

    def test_smt_encodes_authority_types(self):
        with open(SMT_PATH) as f:
            content = f.read()
        for auth_type in ["Control", "DeleteDerived", "Call", "SyncSend"]:
            assert auth_type in content, \
                f"SMT file should encode authority type '{auth_type}'"

    def test_z3_output_exists(self):
        assert os.path.exists(Z3_OUTPUT_PATH), \
            f"Z3 output file not found at {Z3_OUTPUT_PATH}"

    def test_z3_all_properties_verified(self):
        with open(Z3_OUTPUT_PATH) as f:
            content = f.read()
        unsat_count = len(re.findall(r'^unsat$', content, re.MULTILINE))
        assert unsat_count >= 3, (
            f"Expected at least 3 'unsat' results for verified properties, "
            f"got {unsat_count}. Z3 output:\n{content}"
        )

    def test_z3_no_property_failures(self):
        with open(Z3_OUTPUT_PATH) as f:
            content = f.read()
        sat_lines = re.findall(r'^sat$', content, re.MULTILINE)
        assert len(sat_lines) == 0, (
            f"Found {len(sat_lines)} 'sat' result(s) indicating property violation(s). "
            f"Z3 output:\n{content}"
        )
