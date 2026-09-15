
import json
import os
import subprocess
import pytest


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the proof analyzer before tests."""
    result = subprocess.run(
        ["python3", "/app/proof_analyzer.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"proof_analyzer.py failed: {result.stderr}\n{result.stdout}")


@pytest.fixture(scope="session")
def report():
    """Load the analysis report."""
    path = "/app/analysis_report.json"
    assert os.path.isfile(path), "analysis_report.json not found"
    with open(path) as f:
        data = json.load(f)
    return data


# ---------- TCL-resolved design states ----------


class TestDesignStatesResolved:
    def test_file_exists(self):
        assert os.path.isfile("/app/design_states_resolved.json"), (
            "design_states_resolved.json not found - tclsh evaluation likely failed"
        )

    def test_all_state_keys_present(self):
        with open("/app/design_states_resolved.json") as f:
            states = json.load(f)
        expected = {
            "alu.alu_op", "bus_bridge.bridge_state", "cache_ctrl.state",
            "dma_engine.dma_state", "mem_arbiter.priority",
        }
        assert set(states.keys()) == expected

    def test_cache_ctrl_includes_refill(self):
        with open("/app/design_states_resolved.json") as f:
            states = json.load(f)
        assert "REFILL" in states["cache_ctrl.state"], (
            "EXTENDED_CACHE flag should add REFILL"
        )

    def test_alu_op_includes_mul_div(self):
        with open("/app/design_states_resolved.json") as f:
            states = json.load(f)
        assert "MUL" in states["alu.alu_op"], "HAS_MULTIPLY flag should add MUL"
        assert "DIV" in states["alu.alu_op"], "HAS_DIVIDE flag should add DIV"

    def test_alu_op_full_set(self):
        with open("/app/design_states_resolved.json") as f:
            states = json.load(f)
        expected = {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "SRA", "MUL", "DIV"}
        assert set(states["alu.alu_op"]) == expected


# ---------- DOT graph and SVG ----------


class TestDOTGraph:
    def test_dot_file_exists(self):
        assert os.path.isfile("/app/proof_dependency.dot"), (
            "proof_dependency.dot not found"
        )

    def test_svg_file_exists(self):
        assert os.path.isfile("/app/proof_dependency.svg"), (
            "proof_dependency.svg not found - graphviz dot rendering likely failed"
        )

    def test_dot_is_digraph(self):
        with open("/app/proof_dependency.dot") as f:
            content = f.read()
        assert "digraph" in content, "DOT file must be a digraph"

    def test_dot_contains_all_nodes(self):
        with open("/app/proof_dependency.dot") as f:
            content = f.read()
        for i in range(1, 17):
            nid = f"N{i}"
            assert nid in content, f"Node {nid} not found in DOT file"

    def test_dot_edge_count(self):
        with open("/app/proof_dependency.dot") as f:
            lines = f.readlines()
        edges = [l for l in lines if "->" in l]
        assert len(edges) == 11, f"Expected 11 AG dependency edges, got {len(edges)}"

    def test_dot_self_loop_n16(self):
        with open("/app/proof_dependency.dot") as f:
            content = f.read()
        assert "N16 -> N16" in content, "Missing self-loop edge N16 -> N16"

    def test_dot_edge_n1_to_n2(self):
        with open("/app/proof_dependency.dot") as f:
            content = f.read()
        assert "N1 -> N2" in content, "Missing edge N1 -> N2"

    def test_svg_non_empty(self):
        size = os.path.getsize("/app/proof_dependency.svg")
        assert size > 100, f"SVG file too small ({size} bytes), likely invalid"


# ---------- Report structure ----------


class TestReportStructure:
    def test_top_level_keys(self, report):
        required = {
            "assume_guarantee_analysis",
            "case_split_analysis",
            "stopat_analysis",
            "edit_node_analysis",
            "coi",
            "abstraction_soundness",
            "proof_coverage",
            "execution_schedule",
        }
        assert required.issubset(set(report.keys())), (
            f"Missing keys: {required - set(report.keys())}"
        )

    def test_ag_analysis_keys(self, report):
        ag = report["assume_guarantee_analysis"]
        assert "dependency_graph" in ag
        assert "cycles" in ag


# ---------- Assume-Guarantee cycle detection ----------


class TestAssumeGuaranteeCycles:
    def test_dependency_graph_n1(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N1"]) == ["N2", "N3"]

    def test_dependency_graph_n2(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N2"]) == ["N1", "N3"]

    def test_dependency_graph_n3(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N3"]) == ["N4", "N5"]

    def test_dependency_graph_n4(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N4"]) == ["N3"]

    def test_dependency_graph_n5(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N5"]) == ["N3", "N4"]

    def test_dependency_graph_n15(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N15"]) == ["N4"]

    def test_dependency_graph_n16_self(self, report):
        dg = report["assume_guarantee_analysis"]["dependency_graph"]
        assert sorted(dg["N16"]) == ["N16"]

    def test_cycle_count(self, report):
        cycles = report["assume_guarantee_analysis"]["cycles"]
        assert len(cycles) == 3, f"Expected 3 cycles, got {len(cycles)}"

    def test_cycle_n1_n2(self, report):
        cycles = report["assume_guarantee_analysis"]["cycles"]
        cycle_sets = [set(c) for c in cycles]
        assert {"N1", "N2"} in cycle_sets

    def test_cycle_n3_n4_n5(self, report):
        cycles = report["assume_guarantee_analysis"]["cycles"]
        cycle_sets = [set(c) for c in cycles]
        assert {"N3", "N4", "N5"} in cycle_sets

    def test_cycle_n16_self(self, report):
        cycles = report["assume_guarantee_analysis"]["cycles"]
        cycle_sets = [set(c) for c in cycles]
        assert {"N16"} in cycle_sets


# ---------- Case split completeness ----------


class TestCaseSplit:
    def test_n6_incomplete(self, report):
        cs = report["case_split_analysis"]["N6"]
        assert cs["complete"] is False

    def test_n6_state_variable(self, report):
        cs = report["case_split_analysis"]["N6"]
        assert cs["state_variable"] == "cache_ctrl.state"

    def test_n6_missing_refill(self, report):
        cs = report["case_split_analysis"]["N6"]
        assert "REFILL" in cs["missing_values"]

    def test_n6_covered(self, report):
        cs = report["case_split_analysis"]["N6"]
        assert set(cs["covered_values"]) == {"FILL", "IDLE", "LOOKUP", "WRITEBACK"}

    def test_n7_complete(self, report):
        cs = report["case_split_analysis"]["N7"]
        assert cs["complete"] is True

    def test_n7_state_variable(self, report):
        cs = report["case_split_analysis"]["N7"]
        assert cs["state_variable"] == "mem_arbiter.priority"

    def test_n7_no_missing(self, report):
        cs = report["case_split_analysis"]["N7"]
        assert cs["missing_values"] == []

    def test_n8_incomplete(self, report):
        cs = report["case_split_analysis"]["N8"]
        assert cs["complete"] is False

    def test_n8_state_variable(self, report):
        cs = report["case_split_analysis"]["N8"]
        assert cs["state_variable"] == "alu.alu_op"

    def test_n8_missing_mul_div(self, report):
        cs = report["case_split_analysis"]["N8"]
        assert set(cs["missing_values"]) == {"MUL", "DIV"}

    def test_n8_covered_values(self, report):
        cs = report["case_split_analysis"]["N8"]
        expected = {"ADD", "AND", "OR", "SHL", "SHR", "SRA", "SUB", "XOR"}
        assert set(cs["covered_values"]) == expected


# ---------- Stopat validation ----------


class TestStopat:
    def test_n10_valid(self, report):
        sa = report["stopat_analysis"]["N10"]
        assert sa["valid"] is True
        assert sa["errors"] == []

    def test_n11_invalid(self, report):
        sa = report["stopat_analysis"]["N11"]
        assert sa["valid"] is False
        assert len(sa["errors"]) >= 2

    def test_n11_nonexistent_module(self, report):
        sa = report["stopat_analysis"]["N11"]
        errors_lower = [e.lower() for e in sa["errors"]]
        assert any("nonexistent_module" in e for e in errors_lower)

    def test_n11_reg_file_not_child(self, report):
        sa = report["stopat_analysis"]["N11"]
        errors_lower = [e.lower() for e in sa["errors"]]
        assert any("reg_file" in e for e in errors_lower)

    def test_n12_invalid(self, report):
        sa = report["stopat_analysis"]["N12"]
        assert sa["valid"] is False

    def test_n12_alu_not_child(self, report):
        sa = report["stopat_analysis"]["N12"]
        errors_lower = [e.lower() for e in sa["errors"]]
        assert any("alu" in e for e in errors_lower)


# ---------- Edit node validation ----------


class TestEditNode:
    def test_n13_valid(self, report):
        en = report["edit_node_analysis"]["N13"]
        assert en["valid"] is True

    def test_n14_invalid(self, report):
        en = report["edit_node_analysis"]["N14"]
        assert en["valid"] is False

    def test_n14_error_message(self, report):
        en = report["edit_node_analysis"]["N14"]
        errors_lower = [e.lower() for e in en["errors"]]
        assert any("n_nonexistent" in e for e in errors_lower)


# ---------- Cone of Influence ----------


class TestCOI:
    def test_p1_coi(self, report):
        coi = set(report["coi"]["P1"])
        expected = {"alu.op_a", "alu.op_b", "alu.alu_op", "alu.overflow"}
        assert coi == expected, f"P1 COI mismatch: got {coi}"

    def test_p10_coi(self, report):
        coi = set(report["coi"]["P10"])
        expected = {"timer_unit.counter", "timer_unit.prescaler"}
        assert coi == expected

    def test_p3_coi(self, report):
        coi = set(report["coi"]["P3"])
        expected = {
            "mem_arbiter.grant", "mem_arbiter.active_master",
            "mem_arbiter.req_queue", "mem_arbiter.priority",
        }
        assert coi == expected

    def test_p17_coi(self, report):
        coi = set(report["coi"]["P17"])
        expected = {
            "interrupt_ctrl.irq_pending", "interrupt_ctrl.irq_active",
            "interrupt_ctrl.irq_sources",
        }
        assert coi == expected

    def test_p5_coi(self, report):
        coi = set(report["coi"]["P5"])
        expected = {
            "interrupt_ctrl.irq_pending", "interrupt_ctrl.irq_priority",
            "interrupt_ctrl.irq_active", "interrupt_ctrl.irq_sources",
        }
        assert coi == expected

    def test_p2_coi(self, report):
        coi = set(report["coi"]["P2"])
        expected = {
            "cache_ctrl.hit", "cache_ctrl.cpu_ready", "cache_ctrl.state",
            "cache_ctrl.tag_match", "cache_ctrl.valid_bit",
            "tag_ram.tag_data_out", "cache_ctrl.miss",
            "cache_ctrl.evict", "cache_ctrl.fill",
        }
        assert coi == expected

    def test_p12_coi(self, report):
        coi = set(report["coi"]["P12"])
        expected = {
            "reg_file.wr_addr", "reg_file.wr_data", "reg_file.wr_en",
            "reg_file.rd_addr1", "reg_file.rd_data1",
        }
        assert coi == expected

    def test_p7_coi(self, report):
        coi = set(report["coi"]["P7"])
        expected = {
            "bus_bridge.data_buf", "bus_bridge.src_ready",
            "bus_bridge.dst_ready",
        }
        assert coi == expected

    def test_coi_all_properties_present(self, report):
        for i in range(1, 19):
            pid = f"P{i}"
            assert pid in report["coi"], f"Missing COI for {pid}"


# ---------- Abstraction Soundness ----------


class TestAbstractionSoundness:
    def test_section_exists(self, report):
        assert "abstraction_soundness" in report

    def test_n10_unsound(self, report):
        abs_s = report["abstraction_soundness"]["N10"]
        assert abs_s["sound"] is False, (
            "N10 should be unsound: tag_ram.tag_data_out is in P2's COI"
        )

    def test_n10_compromised_signals(self, report):
        abs_s = report["abstraction_soundness"]["N10"]
        assert "tag_ram.tag_data_out" in abs_s["compromised_signals"], (
            "tag_ram.tag_data_out should be flagged as compromised"
        )

    def test_n10_no_missing_modules(self, report):
        abs_s = report["abstraction_soundness"]["N10"]
        assert abs_s["missing_modules"] == []

    def test_n11_unsound(self, report):
        abs_s = report["abstraction_soundness"]["N11"]
        assert abs_s["sound"] is False, (
            "N11 should be unsound due to nonexistent_module"
        )

    def test_n11_missing_module(self, report):
        abs_s = report["abstraction_soundness"]["N11"]
        assert "nonexistent_module" in abs_s["missing_modules"]

    def test_n12_sound(self, report):
        abs_s = report["abstraction_soundness"]["N12"]
        assert abs_s["sound"] is True, (
            "N12 should be sound: no alu signals in P12's COI"
        )
        assert abs_s["compromised_signals"] == []
        assert abs_s["missing_modules"] == []

    def test_all_stopat_nodes_present(self, report):
        abs_s = report["abstraction_soundness"]
        assert "N10" in abs_s
        assert "N11" in abs_s
        assert "N12" in abs_s


# ---------- Proof Coverage ----------


class TestProofCoverage:
    def test_section_exists(self, report):
        assert "proof_coverage" in report

    def test_covered_properties(self, report):
        pc = report["proof_coverage"]
        expected = sorted(["P1", "P2", "P3", "P4", "P5", "P8", "P9", "P10", "P13", "P14", "P15"])
        assert sorted(pc["covered"]) == expected, (
            f"covered mismatch: got {sorted(pc['covered'])}"
        )

    def test_uncovered_properties(self, report):
        pc = report["proof_coverage"]
        expected = sorted(["P6", "P7", "P11", "P12", "P16", "P17", "P18"])
        assert sorted(pc["uncovered"]) == expected, (
            f"uncovered mismatch: got {sorted(pc['uncovered'])}"
        )

    def test_coverage_ratio(self, report):
        pc = report["proof_coverage"]
        assert abs(pc["coverage_ratio"] - 11 / 18) < 0.001, (
            f"Expected coverage_ratio ~0.6111, got {pc['coverage_ratio']}"
        )

    def test_covered_uncovered_exhaustive(self, report):
        pc = report["proof_coverage"]
        all_props = set(pc["covered"]) | set(pc["uncovered"])
        expected = {f"P{i}" for i in range(1, 19)}
        assert all_props == expected, (
            f"Coverage not exhaustive: missing={expected - all_props}"
        )

    def test_covered_uncovered_disjoint(self, report):
        pc = report["proof_coverage"]
        overlap = set(pc["covered"]) & set(pc["uncovered"])
        assert len(overlap) == 0, f"Overlap: {overlap}"


# ---------- Execution schedule ----------


class TestExecutionSchedule:
    def test_schedulable_nodes(self, report):
        sched = report["execution_schedule"]
        assert set(sched["schedulable"]) == {
            "N6", "N7", "N8", "N9", "N10", "N13"
        }

    def test_cyclic_nodes(self, report):
        sched = report["execution_schedule"]
        assert set(sched["cyclic"]) == {
            "N1", "N2", "N3", "N4", "N5", "N16"
        }

    def test_invalid_nodes(self, report):
        sched = report["execution_schedule"]
        assert set(sched["invalid"]) == {"N11", "N12", "N14"}

    def test_blocked_nodes(self, report):
        sched = report["execution_schedule"]
        assert set(sched["blocked"]) == {"N15"}

    def test_all_nodes_classified(self, report):
        sched = report["execution_schedule"]
        all_nodes = set()
        for category in ["schedulable", "cyclic", "invalid", "blocked"]:
            nodes = set(sched[category])
            assert all_nodes.isdisjoint(nodes), (
                f"Overlap in {category}: {all_nodes & nodes}"
            )
            all_nodes |= nodes
        expected = {f"N{i}" for i in range(1, 17)}
        assert all_nodes == expected

    def test_schedulable_sorted(self, report):
        sched = report["execution_schedule"]
        nodes = sched["schedulable"]
        assert nodes == sorted(nodes), "schedulable nodes must be sorted"
