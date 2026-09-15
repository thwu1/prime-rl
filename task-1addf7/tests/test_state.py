
import json
import os
import pytest

RESULTS_DIR = "/app/results"
PROGRAMS = ["null_deref", "packet_oob", "unreachable", "stack_oob", "valid_xdp", "valid_map"]


def load_result(name):
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)


def get_findings_by_type(result, finding_type):
    return [f for f in result["findings"] if f["type"] == finding_type]


# ============================================================
# Result files must exist
# ============================================================
class TestResultsExist:
    @pytest.mark.parametrize("name", PROGRAMS)
    def test_result_file_exists(self, name):
        path = os.path.join(RESULTS_DIR, f"{name}.json")
        assert os.path.exists(path), f"Result file {path} does not exist"

    @pytest.mark.parametrize("name", PROGRAMS)
    def test_result_has_required_fields(self, name):
        result = load_result(name)
        assert "program" in result
        assert "num_instructions" in result
        assert "cfg" in result
        assert "findings" in result
        assert isinstance(result["cfg"], dict)
        assert isinstance(result["findings"], list)


# ============================================================
# Instruction counts verify correct bytecode parsing
# ============================================================
class TestInstructionCounts:
    def test_null_deref_count(self):
        assert load_result("null_deref")["num_instructions"] == 9

    def test_packet_oob_count(self):
        assert load_result("packet_oob")["num_instructions"] == 6

    def test_unreachable_count(self):
        assert load_result("unreachable")["num_instructions"] == 5

    def test_stack_oob_count(self):
        assert load_result("stack_oob")["num_instructions"] == 3

    def test_valid_xdp_count(self):
        assert load_result("valid_xdp")["num_instructions"] == 11

    def test_valid_map_count(self):
        assert load_result("valid_map")["num_instructions"] == 12


# ============================================================
# CFG structure tests
# ============================================================
class TestCFG:
    def test_null_deref_ld_imm64_flows_to_continuation(self):
        """LD_IMM64 at insn 3 must flow to its continuation at insn 4."""
        cfg = load_result("null_deref")["cfg"]
        assert set(cfg["3"]) == {4}
        assert set(cfg["4"]) == {5}

    def test_null_deref_exit_has_no_successors(self):
        cfg = load_result("null_deref")["cfg"]
        assert cfg["8"] == []

    def test_null_deref_call_falls_through(self):
        """CALL at insn 5 must fall through to insn 6."""
        cfg = load_result("null_deref")["cfg"]
        assert set(cfg["5"]) == {6}

    def test_unreachable_unconditional_jump(self):
        """JA at insn 1 with off=2 must jump to insn 4 only."""
        cfg = load_result("unreachable")["cfg"]
        assert set(cfg["1"]) == {4}

    def test_valid_xdp_conditional_branch(self):
        """Conditional JGT at insn 5 must branch to both insn 6 and insn 9."""
        cfg = load_result("valid_xdp")["cfg"]
        assert set(cfg["5"]) == {6, 9}

    def test_valid_xdp_exits(self):
        cfg = load_result("valid_xdp")["cfg"]
        assert cfg["8"] == []
        assert cfg["10"] == []

    def test_valid_map_conditional_branch(self):
        """JEQ at insn 6 must branch to both insn 7 and insn 10."""
        cfg = load_result("valid_map")["cfg"]
        assert set(cfg["6"]) == {7, 10}

    def test_valid_map_exits(self):
        cfg = load_result("valid_map")["cfg"]
        assert cfg["9"] == []
        assert cfg["11"] == []

    def test_all_programs_have_complete_cfg(self):
        """Every instruction index should have a CFG entry."""
        for name in PROGRAMS:
            result = load_result(name)
            n = result["num_instructions"]
            cfg = result["cfg"]
            for i in range(n):
                assert str(i) in cfg, (
                    f"Program {name}: instruction {i} missing from CFG"
                )


# ============================================================
# Finding detection tests
# ============================================================
class TestNullDeref:
    def test_null_deref_detected(self):
        findings = get_findings_by_type(load_result("null_deref"), "null_ptr_deref")
        assert len(findings) >= 1
        assert any(f["instruction"] == 6 for f in findings), (
            "Expected null_ptr_deref at instruction 6 (LDX from R0 without null check)"
        )

    def test_no_null_deref_in_valid_map(self):
        """valid_map has a proper null check -- no false positive."""
        findings = get_findings_by_type(load_result("valid_map"), "null_ptr_deref")
        assert len(findings) == 0, (
            "valid_map has a proper null check; should not flag null_ptr_deref"
        )


class TestPacketBounds:
    def test_packet_oob_detected(self):
        findings = get_findings_by_type(load_result("packet_oob"), "packet_bounds")
        assert len(findings) >= 1
        assert any(f["instruction"] == 3 for f in findings), (
            "Expected packet_bounds at instruction 3 (LDX from packet data without bounds check)"
        )

    def test_no_packet_bounds_in_valid_xdp(self):
        """valid_xdp performs a proper bounds check before packet access."""
        findings = get_findings_by_type(load_result("valid_xdp"), "packet_bounds")
        assert len(findings) == 0, (
            "valid_xdp has proper bounds check; should not flag packet_bounds"
        )


class TestUnreachable:
    def test_unreachable_detected(self):
        findings = get_findings_by_type(load_result("unreachable"), "unreachable_code")
        unreachable_insns = sorted([f["instruction"] for f in findings])
        assert unreachable_insns == [2, 3], (
            f"Expected unreachable_code at instructions [2, 3], got {unreachable_insns}"
        )

    def test_no_unreachable_in_valid_xdp(self):
        findings = get_findings_by_type(load_result("valid_xdp"), "unreachable_code")
        assert len(findings) == 0

    def test_no_unreachable_in_valid_map(self):
        findings = get_findings_by_type(load_result("valid_map"), "unreachable_code")
        assert len(findings) == 0


class TestStackOOB:
    def test_stack_oob_detected(self):
        findings = get_findings_by_type(load_result("stack_oob"), "stack_out_of_bounds")
        assert len(findings) >= 1
        assert any(f["instruction"] == 0 for f in findings), (
            "Expected stack_out_of_bounds at instruction 0 (store to r10-516)"
        )

    def test_no_stack_oob_in_null_deref(self):
        """null_deref accesses r10-4, which is within bounds."""
        findings = get_findings_by_type(load_result("null_deref"), "stack_out_of_bounds")
        assert len(findings) == 0

    def test_no_stack_oob_in_valid_map(self):
        findings = get_findings_by_type(load_result("valid_map"), "stack_out_of_bounds")
        assert len(findings) == 0


# ============================================================
# Valid programs must have zero findings
# ============================================================
class TestValidPrograms:
    def test_valid_xdp_no_findings(self):
        result = load_result("valid_xdp")
        assert len(result["findings"]) == 0, (
            f"valid_xdp should have no findings, got: {result['findings']}"
        )

    def test_valid_map_no_findings(self):
        result = load_result("valid_map")
        assert len(result["findings"]) == 0, (
            f"valid_map should have no findings, got: {result['findings']}"
        )
