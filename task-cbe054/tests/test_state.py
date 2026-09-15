"""
Verification tests for OSPF Conformance Test Suite.
"""

import json
import os
import pytest
import jsonschema


# --- Helper ---

def load_json_file(path):
    with open(path) as f:
        return json.load(f)


# --- Corrected FSM Tests ---

class TestCorrectedFSM:

    def test_fsm_exists(self):
        assert os.path.exists("/app/output/fsm.json"), \
            "fsm.json not found in /app/output/"

    def test_has_eight_states(self):
        fsm = load_json_file("/app/output/fsm.json")
        expected = {"Down", "Attempt", "Init", "TwoWay", "ExStart", "Exchange", "Loading", "Full"}
        assert set(fsm["states"]) == expected

    def test_has_thirteen_events(self):
        fsm = load_json_file("/app/output/fsm.json")
        assert len(fsm["events"]) == 13

    def test_no_wildcard_transitions(self):
        fsm = load_json_file("/app/output/fsm.json")
        for t in fsm["transitions"]:
            assert t["from"] != "*", \
                f"Wildcard found in transition: {t}"

    def test_expanded_transition_count(self):
        fsm = load_json_file("/app/output/fsm.json")
        assert len(fsm["transitions"]) == 49, \
            f"Expected 49 transitions, got {len(fsm['transitions'])}"

    def test_correction_attempt_hello(self):
        """Attempt + HelloReceived -> Init must be present."""
        fsm = load_json_file("/app/output/fsm.json")
        found = any(
            t["from"] == "Attempt" and t["event"] == "HelloReceived" and t["to"] == "Init"
            for t in fsm["transitions"]
        )
        assert found, "Missing: Attempt + HelloReceived -> Init"

    def test_correction_exchange_done_conditional(self):
        """Exchange + ExchangeDone should branch to Loading and Full."""
        fsm = load_json_file("/app/output/fsm.json")
        exchange_done = [
            t for t in fsm["transitions"]
            if t["from"] == "Exchange" and t["event"] == "ExchangeDone"
        ]
        targets = {t["to"] for t in exchange_done}
        assert "Loading" in targets, \
            "Missing: Exchange + ExchangeDone -> Loading"
        assert "Full" in targets, \
            "Missing: Exchange + ExchangeDone -> Full"

    def test_correction_loading_seq_mismatch(self):
        """Loading + SeqNumberMismatch -> ExStart must be present."""
        fsm = load_json_file("/app/output/fsm.json")
        found = any(
            t["from"] == "Loading" and t["event"] == "SeqNumberMismatch" and t["to"] == "ExStart"
            for t in fsm["transitions"]
        )
        assert found, "Missing: Loading + SeqNumberMismatch -> ExStart"

    def test_correction_full_bad_ls_req(self):
        """Full + BadLSReq -> ExStart must be present."""
        fsm = load_json_file("/app/output/fsm.json")
        found = any(
            t["from"] == "Full" and t["event"] == "BadLSReq" and t["to"] == "ExStart"
            for t in fsm["transitions"]
        )
        assert found, "Missing: Full + BadLSReq -> ExStart"

    def test_correction_full_one_way(self):
        """Full + OneWay -> Init must be present."""
        fsm = load_json_file("/app/output/fsm.json")
        found = any(
            t["from"] == "Full" and t["event"] == "OneWay" and t["to"] == "Init"
            for t in fsm["transitions"]
        )
        assert found, "Missing: Full + OneWay -> Init"

    def test_correction_exchange_adjok_demotion(self):
        """Exchange + AdjOK -> TwoWay must be present."""
        fsm = load_json_file("/app/output/fsm.json")
        found = any(
            t["from"] == "Exchange" and t["event"] == "AdjOK" and t["to"] == "TwoWay"
            for t in fsm["transitions"]
        )
        assert found, "Missing: Exchange + AdjOK -> TwoWay"

    def test_validates_against_schema(self):
        fsm = load_json_file("/app/output/fsm.json")
        schema = load_json_file("/app/schemas/fsm_schema.json")
        jsonschema.validate(fsm, schema)


# --- Topology Tests ---

class TestTopology:

    def test_topology_exists(self):
        assert os.path.exists("/app/output/topology.json")

    def test_topology_schema_valid(self):
        topo = load_json_file("/app/output/topology.json")
        schema = load_json_file("/app/schemas/topology_schema.json")
        jsonschema.validate(topo, schema)

    def test_three_routers(self):
        topo = load_json_file("/app/output/topology.json")
        assert len(topo["routers"]) == 3, \
            f"Expected 3 routers, got {len(topo['routers'])}"

    def test_router_ids(self):
        topo = load_json_file("/app/output/topology.json")
        ids = {r["router_id"] for r in topo["routers"]}
        assert ids == {"10.0.0.1", "10.0.0.2", "10.0.0.3"}

    def test_three_links(self):
        topo = load_json_file("/app/output/topology.json")
        assert len(topo["links"]) == 3, \
            f"Expected 3 links, got {len(topo['links'])}"

    def test_has_point_to_point_link(self):
        topo = load_json_file("/app/output/topology.json")
        p2p = [l for l in topo["links"] if l["network_type"] == "point-to-point"]
        assert len(p2p) >= 1, "No point-to-point link found"

    def test_has_broadcast_link(self):
        topo = load_json_file("/app/output/topology.json")
        bcast = [l for l in topo["links"] if l["network_type"] == "broadcast"]
        assert len(bcast) >= 1, "No broadcast link found"

    def test_multi_area(self):
        topo = load_json_file("/app/output/topology.json")
        areas = set()
        for link in topo["links"]:
            areas.add(link["area"])
        assert len(areas) >= 2, \
            f"Expected at least 2 areas, got {areas}"


# --- FSM Diagram Tests ---

class TestFSMDiagram:

    def test_diagram_exists(self):
        assert os.path.exists("/app/output/fsm_diagram.svg"), \
            "fsm_diagram.svg not found"

    def test_diagram_is_svg(self):
        with open("/app/output/fsm_diagram.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), "File does not contain SVG tag"
        assert "</svg>" in content.lower(), "SVG tag is not closed"

    def test_diagram_has_all_states(self):
        with open("/app/output/fsm_diagram.svg") as f:
            content = f.read()
        for state in ["Down", "Attempt", "Init", "TwoWay",
                       "ExStart", "Exchange", "Loading", "Full"]:
            assert state in content, \
                f"State '{state}' not found in diagram"

    def test_diagram_has_transition_labels(self):
        with open("/app/output/fsm_diagram.svg") as f:
            content = f.read()
        events_found = sum(
            1 for e in ["HelloReceived", "KillNbr", "LLDown",
                        "ExchangeDone", "NegotiationDone"]
            if e in content
        )
        assert events_found >= 3, \
            "Diagram should contain transition event labels"

    def test_diagram_generated_by_graphviz(self):
        with open("/app/output/fsm_diagram.svg") as f:
            content = f.read()
        assert "graphviz" in content.lower() or "Generated by" in content, \
            "SVG does not appear to be generated by Graphviz"


# --- Coverage Before Tests ---

class TestCoverageBefore:

    def test_coverage_before_exists(self):
        assert os.path.exists("/app/output/coverage_before.json")

    def test_coverage_before_low(self):
        cov = load_json_file("/app/output/coverage_before.json")
        assert cov["coverage_percentage"] < 40, \
            f"Coverage before should be < 40%, got {cov['coverage_percentage']}%"

    def test_coverage_before_has_uncovered(self):
        cov = load_json_file("/app/output/coverage_before.json")
        assert len(cov["uncovered_transitions"]) > 0

    def test_coverage_before_schema(self):
        cov = load_json_file("/app/output/coverage_before.json")
        schema = load_json_file("/app/schemas/coverage_schema.json")
        jsonschema.validate(cov, schema)


# --- Test Suite Tests ---

class TestTestSuite:

    def test_test_suite_exists(self):
        assert os.path.exists("/app/output/test_suite.json")

    def test_test_suite_nonempty(self):
        tests = load_json_file("/app/output/test_suite.json")
        assert len(tests["test_cases"]) > 0, "No test cases generated"

    def test_test_suite_schema_valid(self):
        tests = load_json_file("/app/output/test_suite.json")
        schema = load_json_file("/app/schemas/test_case_schema.json")
        jsonschema.validate(tests, schema)

    def test_tests_have_transitions(self):
        tests = load_json_file("/app/output/test_suite.json")
        for tc in tests["test_cases"]:
            assert len(tc["fsm_transitions"]) > 0, \
                f"Test case {tc['id']} has empty fsm_transitions"

    def test_tests_have_steps(self):
        tests = load_json_file("/app/output/test_suite.json")
        for tc in tests["test_cases"]:
            assert len(tc["steps"]) > 0, \
                f"Test case {tc['id']} has empty steps"

    def test_tests_unique_ids(self):
        tests = load_json_file("/app/output/test_suite.json")
        ids = [tc["id"] for tc in tests["test_cases"]]
        assert len(ids) == len(set(ids)), "Duplicate test case IDs found"

    def test_tests_topology_aware(self):
        tests = load_json_file("/app/output/test_suite.json")
        text = json.dumps(tests).lower()
        topo_terms = ["router1", "router2", "router3",
                      "10.0.0.", "broadcast", "point-to-point"]
        found = sum(1 for term in topo_terms if term in text)
        assert found >= 2, \
            "Generated tests should reference topology elements"


# --- Coverage After Tests ---

class TestCoverageAfter:

    def test_coverage_after_exists(self):
        assert os.path.exists("/app/output/coverage_after.json")

    def test_coverage_improved(self):
        before = load_json_file("/app/output/coverage_before.json")
        after = load_json_file("/app/output/coverage_after.json")
        assert after["coverage_percentage"] > before["coverage_percentage"], \
            f"Coverage did not improve: {before['coverage_percentage']}% -> {after['coverage_percentage']}%"

    def test_coverage_after_threshold(self):
        cov = load_json_file("/app/output/coverage_after.json")
        assert cov["coverage_percentage"] >= 80, \
            f"Coverage after should be >= 80%, got {cov['coverage_percentage']}%"

    def test_coverage_after_schema(self):
        cov = load_json_file("/app/output/coverage_after.json")
        schema = load_json_file("/app/schemas/coverage_schema.json")
        jsonschema.validate(cov, schema)


# --- Pipeline Tests ---

class TestPipeline:

    def test_pipeline_script_exists(self):
        assert os.path.exists("/app/run_pipeline.py"), \
            "Pipeline entry point /app/run_pipeline.py not found"
