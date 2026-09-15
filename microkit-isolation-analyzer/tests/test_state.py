
import json
import os
import re
import pytest


REPORT_PATH = "/app/report.json"
DOT_PATH = "/app/dependency_graph.dot"
SVG_PATH = "/app/dependency_graph.svg"
CRITICAL_PATHS_PATH = "/app/critical_paths.json"

ALL_PDS = sorted([
    "actuator", "config_store", "control", "crypto", "eth_driver",
    "guest_os", "logger", "net_mux", "sensor", "serial_driver",
    "telemetry", "vmm"
])

ALL_PDS_SET = set(ALL_PDS)

EXPECTED_DEPS = {
    "actuator": ["control"],
    "config_store": [],
    "control": ["actuator", "config_store", "sensor"],
    "crypto": ["telemetry"],
    "eth_driver": ["net_mux"],
    "guest_os": ["vmm"],
    "logger": ["sensor", "serial_driver"],
    "net_mux": ["eth_driver", "telemetry", "vmm"],
    "sensor": ["control", "logger"],
    "serial_driver": ["logger"],
    "telemetry": ["control", "crypto", "net_mux"],
    "vmm": ["guest_os", "net_mux"],
}

EXPECTED_TCB_SIZES = {
    "actuator": 5,
    "config_store": 0,
    "control": 5,
    "crypto": 11,
    "eth_driver": 11,
    "guest_os": 11,
    "logger": 5,
    "net_mux": 11,
    "sensor": 5,
    "serial_driver": 5,
    "telemetry": 11,
    "vmm": 11,
}

EXPECTED_IMPACT_SIZES = {
    "actuator": 10,
    "config_store": 11,
    "control": 10,
    "crypto": 5,
    "eth_driver": 5,
    "guest_os": 5,
    "logger": 10,
    "net_mux": 5,
    "sensor": 10,
    "serial_driver": 10,
    "telemetry": 5,
    "vmm": 5,
}


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"{REPORT_PATH} does not exist"
    with open(REPORT_PATH) as f:
        return json.load(f)


class TestProtectionDomains:
    def test_pd_list(self, report):
        """All 12 protection domains are present and sorted."""
        assert report["protection_domains"] == ALL_PDS

    def test_pd_count(self, report):
        """Exactly 12 protection domains."""
        assert len(report["protection_domains"]) == 12


class TestDependencyGraph:
    def test_control_direct_deps(self, report):
        """Control depends on sensor (channel+memory), actuator (channel),
        config_store (memory)."""
        assert sorted(report["dependency_graph"]["control"]) == \
            ["actuator", "config_store", "sensor"]

    def test_config_store_no_deps(self, report):
        """config_store has no outgoing dependencies."""
        assert report["dependency_graph"]["config_store"] == []

    def test_telemetry_depends_on_control(self, report):
        """Telemetry depends on control through ctrl_status memory
        (control writes, telemetry reads)."""
        assert "control" in report["dependency_graph"]["telemetry"]

    def test_control_does_not_depend_on_telemetry(self, report):
        """Control does NOT depend on telemetry (telemetry only reads
        ctrl_status - asymmetric dependency)."""
        assert "telemetry" not in report["dependency_graph"]["control"]

    def test_guest_os_depends_on_vmm(self, report):
        """guest_os depends on vmm (parent-child + shared guest_ram)."""
        assert "vmm" in report["dependency_graph"]["guest_os"]

    def test_vmm_depends_on_guest_os(self, report):
        """vmm depends on guest_os (guest_os can write to guest_ram)."""
        assert "guest_os" in report["dependency_graph"]["vmm"]

    def test_actuator_single_dep(self, report):
        """Actuator only depends on control."""
        assert report["dependency_graph"]["actuator"] == ["control"]

    def test_sensor_deps(self, report):
        """Sensor depends on control AND logger — control via channel
        (NOT just memory), logger via channel. FINDING-4 in the cert
        report is incorrect: the channel creates a bidirectional dep."""
        assert sorted(report["dependency_graph"]["sensor"]) == \
            ["control", "logger"]

    def test_all_deps_match(self, report):
        """Full dependency graph matches expected."""
        for pd in ALL_PDS:
            actual = sorted(report["dependency_graph"].get(pd, []))
            expected = EXPECTED_DEPS[pd]
            assert actual == expected, \
                f"Deps of {pd}: expected {expected}, got {actual}"


class TestTCB:
    def test_tcb_sizes(self, report):
        """Verify TCB sizes for all PDs."""
        for pd in ALL_PDS:
            actual = len(report["tcb"][pd])
            expected = EXPECTED_TCB_SIZES[pd]
            assert actual == expected, \
                f"TCB size of {pd}: expected {expected}, got {actual}"

    def test_control_tcb_excludes_network(self, report):
        """Control's TCB must NOT include any network/VM PDs."""
        network_pds = {"eth_driver", "net_mux", "telemetry", "crypto",
                       "vmm", "guest_os"}
        control_tcb = set(report["tcb"]["control"])
        assert control_tcb.isdisjoint(network_pds), \
            f"Control TCB incorrectly includes: {control_tcb & network_pds}"

    def test_control_tcb_contents(self, report):
        """Control's TCB is exactly the safety-critical cluster minus control."""
        expected = sorted(["actuator", "config_store", "logger", "sensor",
                           "serial_driver"])
        assert sorted(report["tcb"]["control"]) == expected

    def test_guest_os_tcb_includes_control(self, report):
        """guest_os's TCB must include control (via telemetry -> control
        memory dependency chain)."""
        assert "control" in report["tcb"]["guest_os"]

    def test_config_store_empty_tcb(self, report):
        """config_store depends on nothing."""
        assert report["tcb"]["config_store"] == []

    def test_network_pd_full_tcb(self, report):
        """Network PDs should have TCB containing all 11 other PDs."""
        for pd in ["eth_driver", "net_mux", "telemetry", "crypto",
                    "vmm", "guest_os"]:
            expected = sorted([p for p in ALL_PDS if p != pd])
            assert sorted(report["tcb"][pd]) == expected, \
                f"TCB of {pd} should include all other PDs"


class TestImpactBoundary:
    def test_impact_sizes(self, report):
        """Verify impact boundary sizes for all PDs."""
        for pd in ALL_PDS:
            actual = len(report["impact_boundary"][pd])
            expected = EXPECTED_IMPACT_SIZES[pd]
            assert actual == expected, \
                f"Impact size of {pd}: expected {expected}, got {actual}"

    def test_config_store_max_impact(self, report):
        """config_store affects all 11 other PDs (everything depends on it
        transitively through control)."""
        assert len(report["impact_boundary"]["config_store"]) == 11

    def test_eth_driver_limited_impact(self, report):
        """eth_driver only affects the network cluster (5 PDs)."""
        expected = sorted(["crypto", "guest_os", "net_mux", "telemetry",
                           "vmm"])
        assert sorted(report["impact_boundary"]["eth_driver"]) == expected

    def test_config_store_impacts_everyone(self, report):
        """config_store's impact is ALL other PDs."""
        assert set(report["impact_boundary"]["config_store"]) == \
            set(ALL_PDS) - {"config_store"}

    def test_impact_differs_from_tcb(self, report):
        """Impact boundary must NOT equal TCB for PDs with asymmetric
        reachability (this catches Bug C where impact used dep_graph)."""
        mismatches = 0
        for pd in ALL_PDS:
            tcb_set = set(report["tcb"][pd])
            impact_set = set(report["impact_boundary"][pd])
            if tcb_set != impact_set:
                mismatches += 1
        assert mismatches > 0, \
            "Impact boundary equals TCB for all PDs — likely using " \
            "dep_graph instead of tcb for impact computation"


class TestSharedResources:
    def test_sensor_data_asymmetric(self, report):
        """sensor_data: sensor writes, control reads."""
        sr = report["shared_resources"]["sensor_data"]
        assert sr["writers"] == ["sensor"]
        assert sr["readers"] == ["control"]

    def test_eth_rx_symmetric(self, report):
        """eth_rx: both eth_driver and net_mux write."""
        sr = report["shared_resources"]["eth_rx"]
        assert sorted(sr["writers"]) == ["eth_driver", "net_mux"]
        assert sr["readers"] == []

    def test_config_data_asymmetric(self, report):
        """config_data: config_store writes, control reads."""
        sr = report["shared_resources"]["config_data"]
        assert sr["writers"] == ["config_store"]
        assert sr["readers"] == ["control"]

    def test_guest_ram_shared(self, report):
        """guest_ram: both vmm and guest_os write."""
        sr = report["shared_resources"]["guest_ram"]
        assert sorted(sr["writers"]) == ["guest_os", "vmm"]
        assert sr["readers"] == []

    def test_all_shared_regions_present(self, report):
        """All 14 shared memory regions should be present."""
        expected_regions = sorted([
            "sensor_data", "actuator_cmd", "ctrl_status", "sensor_diag",
            "eth_rx", "eth_tx", "net_telem_rx", "net_telem_tx",
            "net_vm_rx", "net_vm_tx", "crypto_buf", "serial_buf",
            "config_data", "guest_ram"
        ])
        assert sorted(report["shared_resources"].keys()) == expected_regions


class TestPolicyViolations:
    def test_isolation_violation_count(self, report):
        """All 3 isolation pairs are violated."""
        assert len(report["policy_violations"]["isolation_violations"]) == 3

    def test_isolation_violation_pairs(self, report):
        """The violated pairs are control-guest_os, control-vmm,
        actuator-guest_os."""
        violated_pairs = sorted(
            [tuple(v["pair"])
             for v in report["policy_violations"]["isolation_violations"]]
        )
        expected = sorted([
            ("actuator", "guest_os"),
            ("control", "guest_os"),
            ("control", "vmm"),
        ])
        assert violated_pairs == expected

    def test_isolation_violation_direction(self, report):
        """For control-guest_os: control is in TCB of guest_os,
        but guest_os is NOT in TCB of control."""
        for v in report["policy_violations"]["isolation_violations"]:
            if v["pair"] == ["control", "guest_os"]:
                assert v["first_in_tcb_of_second"] is True
                assert v["second_in_tcb_of_first"] is False
                return
        pytest.fail("control-guest_os violation not found")

    def test_no_tcb_size_violations(self, report):
        """No TCB size violations (all safety PDs have TCB size 5,
        limits are 6)."""
        assert len(report["policy_violations"]["tcb_size_violations"]) == 0

    def test_impact_size_violation_count(self, report):
        """3 impact size violations (guest_os, vmm, telemetry)."""
        assert len(report["policy_violations"]["impact_size_violations"]) == 3

    def test_impact_size_violation_details(self, report):
        """Verify specific impact size violations."""
        violations = {v["pd"]: v
                      for v in report["policy_violations"][
                          "impact_size_violations"]}
        assert "guest_os" in violations
        assert violations["guest_os"]["actual_size"] == 5
        assert violations["guest_os"]["max_allowed"] == 3
        assert "vmm" in violations
        assert violations["vmm"]["actual_size"] == 5
        assert violations["vmm"]["max_allowed"] == 3
        assert "telemetry" in violations
        assert violations["telemetry"]["actual_size"] == 5
        assert violations["telemetry"]["max_allowed"] == 4


class TestDependencyDOT:
    """Tests for the Graphviz DOT dependency graph file."""

    @pytest.fixture
    def dot_edges(self):
        assert os.path.exists(DOT_PATH), f"{DOT_PATH} does not exist"
        with open(DOT_PATH) as f:
            content = f.read()
        assert "digraph" in content.lower(), \
            "DOT file must contain a digraph declaration"
        raw_edges = re.findall(r'"?(\w+)"?\s*->\s*"?(\w+)"?', content)
        return set((a, b) for a, b in raw_edges
                   if a in ALL_PDS_SET and b in ALL_PDS_SET)

    def test_dot_file_exists(self):
        """DOT file must exist."""
        assert os.path.exists(DOT_PATH), f"{DOT_PATH} does not exist"

    def test_dot_correct_edge_count(self, dot_edges):
        """Dependency graph has exactly 20 direct edges."""
        assert len(dot_edges) == 20, \
            f"Expected 20 edges, got {len(dot_edges)}: {sorted(dot_edges)}"

    def test_dot_control_depends_on_sensor(self, dot_edges):
        """control -> sensor edge must be present."""
        assert ("control", "sensor") in dot_edges

    def test_dot_control_depends_on_config_store(self, dot_edges):
        """control -> config_store edge must be present."""
        assert ("control", "config_store") in dot_edges

    def test_dot_telemetry_depends_on_control(self, dot_edges):
        """telemetry -> control edge must be present (asymmetric memory)."""
        assert ("telemetry", "control") in dot_edges

    def test_dot_control_not_depends_on_telemetry(self, dot_edges):
        """control -> telemetry edge must NOT be present (buggy edge)."""
        assert ("control", "telemetry") not in dot_edges

    def test_dot_config_store_no_outgoing(self, dot_edges):
        """config_store must have no outgoing edges."""
        config_out = [e for e in dot_edges if e[0] == "config_store"]
        assert len(config_out) == 0, \
            f"config_store has unexpected outgoing edges: {config_out}"

    def test_dot_guest_os_depends_on_vmm(self, dot_edges):
        """guest_os -> vmm edge must be present."""
        assert ("guest_os", "vmm") in dot_edges

    def test_dot_sensor_depends_on_control(self, dot_edges):
        """sensor -> control edge must be present (via channel, NOT
        removed per incorrect FINDING-4)."""
        assert ("sensor", "control") in dot_edges

    def test_dot_all_pds_appear(self, dot_edges):
        """All 12 PDs must appear as nodes in at least one edge."""
        nodes = set()
        for a, b in dot_edges:
            nodes.add(a)
            nodes.add(b)
        assert nodes == ALL_PDS_SET, \
            f"Missing PDs in DOT: {ALL_PDS_SET - nodes}"


class TestSVG:
    """Tests for the rendered SVG dependency graph."""

    def test_svg_exists(self):
        """SVG file must exist."""
        assert os.path.exists(SVG_PATH), \
            f"{SVG_PATH} does not exist — must render DOT with dot CLI"

    def test_svg_is_valid(self):
        """SVG file must contain valid SVG markup."""
        with open(SVG_PATH) as f:
            content = f.read()
        assert "<svg" in content.lower(), "SVG file missing <svg> tag"
        assert "</svg>" in content.lower(), "SVG file missing </svg> tag"

    def test_svg_generated_by_graphviz(self):
        """SVG should be generated by graphviz dot tool."""
        with open(SVG_PATH) as f:
            content = f.read()
        assert "graphviz" in content.lower() or "Generated by" in content, \
            "SVG does not appear to be generated by graphviz"

    def test_svg_contains_all_pds(self):
        """SVG must reference all 12 protection domains."""
        with open(SVG_PATH) as f:
            content = f.read()
        for pd in ALL_PDS:
            assert pd in content, \
                f"PD '{pd}' not found in rendered SVG"


class TestCriticalPaths:
    """Tests for the critical dependency chain analysis."""

    @pytest.fixture
    def critical_paths(self):
        assert os.path.exists(CRITICAL_PATHS_PATH), \
            f"{CRITICAL_PATHS_PATH} does not exist"
        with open(CRITICAL_PATHS_PATH) as f:
            return json.load(f)

    def test_file_exists(self):
        """Critical paths JSON must exist."""
        assert os.path.exists(CRITICAL_PATHS_PATH)

    def test_has_required_key(self, critical_paths):
        """Must have isolation_violation_paths key."""
        assert "isolation_violation_paths" in critical_paths

    def test_violation_count(self, critical_paths):
        """Exactly 3 isolation violation paths."""
        assert len(critical_paths["isolation_violation_paths"]) == 3

    def test_actuator_guest_os_path(self, critical_paths):
        """Shortest path for actuator in TCB of guest_os."""
        paths = critical_paths["isolation_violation_paths"]
        entry = next(
            (p for p in paths if p["pair"] == ["actuator", "guest_os"]),
            None
        )
        assert entry is not None, "Missing path for actuator-guest_os"
        assert entry["path"] == [
            "guest_os", "vmm", "net_mux", "telemetry", "control", "actuator"
        ]

    def test_control_guest_os_path(self, critical_paths):
        """Shortest path for control in TCB of guest_os."""
        paths = critical_paths["isolation_violation_paths"]
        entry = next(
            (p for p in paths if p["pair"] == ["control", "guest_os"]),
            None
        )
        assert entry is not None, "Missing path for control-guest_os"
        assert entry["path"] == [
            "guest_os", "vmm", "net_mux", "telemetry", "control"
        ]

    def test_control_vmm_path(self, critical_paths):
        """Shortest path for control in TCB of vmm."""
        paths = critical_paths["isolation_violation_paths"]
        entry = next(
            (p for p in paths if p["pair"] == ["control", "vmm"]),
            None
        )
        assert entry is not None, "Missing path for control-vmm"
        assert entry["path"] == [
            "vmm", "net_mux", "telemetry", "control"
        ]

    def test_paths_are_valid_dep_chains(self, report, critical_paths):
        """Each step in every path must be a valid dependency edge."""
        dep_graph = report["dependency_graph"]
        for entry in critical_paths["isolation_violation_paths"]:
            path = entry["path"]
            for i in range(len(path) - 1):
                src, dst = path[i], path[i + 1]
                assert dst in dep_graph.get(src, []), \
                    f"Invalid dep edge {src}->{dst} in path " \
                    f"for violation {entry['pair']}"

    def test_paths_sorted_by_pair(self, critical_paths):
        """Violation paths must be sorted by pair (alphabetically)."""
        paths = critical_paths["isolation_violation_paths"]
        pairs = [tuple(p["pair"]) for p in paths]
        assert pairs == sorted(pairs)

    def test_path_endpoints(self, critical_paths):
        """Each path must start at the dependent PD and end at the
        PD found in TCB."""
        expected_endpoints = {
            ("actuator", "guest_os"): ("guest_os", "actuator"),
            ("control", "guest_os"): ("guest_os", "control"),
            ("control", "vmm"): ("vmm", "control"),
        }
        for entry in critical_paths["isolation_violation_paths"]:
            pair_key = tuple(entry["pair"])
            expected_start, expected_end = expected_endpoints[pair_key]
            assert entry["path"][0] == expected_start, \
                f"Path for {pair_key} should start at {expected_start}"
            assert entry["path"][-1] == expected_end, \
                f"Path for {pair_key} should end at {expected_end}"
