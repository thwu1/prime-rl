
"""
Verification tests for the TTCN-3 SIP Conformance Test Suite Static Analyzer.
Checks that analysis_results.json contains correct structural defect findings.
"""

import json
import os
import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/analysis_results.json"
    assert os.path.isfile(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


class TestStructure:
    def test_top_level_keys(self, results):
        for key in ["testcase_definitions", "control_block", "defects", "rfc_coverage"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_testcase_definitions_keys(self, results):
        defs = results["testcase_definitions"]
        assert "total" in defs, "Missing 'total' in testcase_definitions"
        assert isinstance(defs["total"], int)

    def test_control_block_keys(self, results):
        cb = results["control_block"]
        assert "active_executions" in cb
        assert "voided_testcases" in cb
        assert isinstance(cb["active_executions"], int)
        assert isinstance(cb["voided_testcases"], list)

    def test_defects_keys(self, results):
        defects = results["defects"]
        assert "guard_mismatches" in defects
        assert "duplicate_guards" in defects
        assert isinstance(defects["guard_mismatches"], list)
        assert isinstance(defects["duplicate_guards"], list)

    def test_rfc_coverage_is_dict(self, results):
        assert isinstance(results["rfc_coverage"], dict)


class TestTestcaseCounts:
    def test_total_testcases_reasonable(self, results):
        total = results["testcase_definitions"]["total"]
        assert total >= 400, f"Expected >= 400 total testcases, got {total}"
        assert total <= 500, f"Expected <= 500 total testcases, got {total}"

    def test_module_counts_sum_to_total(self, results):
        defs = results["testcase_definitions"]
        module_sum = sum(v for k, v in defs.items() if k != "total")
        assert module_sum == defs["total"], (
            f"Module counts sum ({module_sum}) != total ({defs['total']})"
        )

    def test_registration_module_count(self, results):
        defs = results["testcase_definitions"]
        reg_count = defs.get("SIP_Registration", 0)
        assert 50 <= reg_count <= 60, (
            f"Expected 50-60 registration testcases, got {reg_count}"
        )

    def test_callcontrol_module_count(self, results):
        defs = results["testcase_definitions"]
        cc_count = defs.get("SIP_CallControl", 0)
        assert 370 <= cc_count <= 390, (
            f"Expected 370-390 call control testcases, got {cc_count}"
        )


class TestControlBlock:
    def test_active_executions_count(self, results):
        count = results["control_block"]["active_executions"]
        assert 515 <= count <= 530, (
            f"Expected 515-530 active executions, got {count}"
        )

    def test_voided_stf296_rg_rt_v_006(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        assert "SIP_RG_RT_V_006" in voided, (
            "SIP_RG_RT_V_006 should be voided (STF296)"
        )

    def test_voided_stf296_cc_pr_mp_rq_v_010(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        assert "SIP_CC_PR_MP_RQ_V_010" in voided, (
            "SIP_CC_PR_MP_RQ_V_010 should be voided (STF296)"
        )

    def test_voided_stf296_cc_pr_mp_rq_v_028(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        assert "SIP_CC_PR_MP_RQ_V_028" in voided, (
            "SIP_CC_PR_MP_RQ_V_028 should be voided (STF296)"
        )

    def test_voided_stf296_cc_pr_tr_cl_ti_006(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        assert "SIP_CC_PR_TR_CL_TI_006" in voided, (
            "SIP_CC_PR_TR_CL_TI_006 should be voided (STF296)"
        )

    def test_voided_stf296_cc_pr_tr_cl_ti_011(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        assert "SIP_CC_PR_TR_CL_TI_011" in voided, (
            "SIP_CC_PR_TR_CL_TI_011 should be voided (STF296)"
        )

    def test_voided_mg_oe_v_011(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        assert "SIP_MG_OE_V_011" in voided, (
            "SIP_MG_OE_V_011 should be voided (commented out)"
        )

    def test_voided_count_minimum(self, results):
        voided = results["control_block"]["voided_testcases"]
        assert len(voided) >= 6, (
            f"Expected at least 6 voided testcases, got {len(voided)}"
        )

    def test_active_not_in_voided(self, results):
        voided = set(results["control_block"]["voided_testcases"])
        for tc in ["SIP_RG_RT_V_001", "SIP_CC_OE_CE_V_001",
                    "SIP_CC_TE_CE_V_001"]:
            assert tc not in voided, f"{tc} should not be voided"


class TestDuplicateGuards:
    def test_ccprmprqi001_duplicate(self, results):
        dupes = results["defects"]["duplicate_guards"]
        dupe_guards = {d["guard_function"] for d in dupes}
        assert "runCCPRMPRQI001" in dupe_guards, (
            "runCCPRMPRQI001 should be detected as duplicate guard"
        )

    def test_ccprmprqi001_testcases(self, results):
        dupes = results["defects"]["duplicate_guards"]
        for d in dupes:
            if d["guard_function"] == "runCCPRMPRQI001":
                tcs = set(d["testcases"])
                assert "SIP_CC_PR_MP_RQ_I_001" in tcs
                assert "SIP_CC_PR_MP_RQ_I_002" in tcs
                return
        pytest.fail("runCCPRMPRQI001 duplicate not found")

    def test_mgpri004_duplicate(self, results):
        dupes = results["defects"]["duplicate_guards"]
        dupe_guards = {d["guard_function"] for d in dupes}
        assert "runMGPRI004" in dupe_guards, (
            "runMGPRI004 should be detected as duplicate guard"
        )

    def test_mgpri004_testcases(self, results):
        dupes = results["defects"]["duplicate_guards"]
        for d in dupes:
            if d["guard_function"] == "runMGPRI004":
                tcs = set(d["testcases"])
                assert "SIP_MG_PR_I_003" in tcs
                assert "SIP_MG_PR_I_004" in tcs
                return
        pytest.fail("runMGPRI004 duplicate not found")

    def test_duplicate_count(self, results):
        dupes = results["defects"]["duplicate_guards"]
        assert len(dupes) >= 2, f"Expected >= 2 duplicate guards, got {len(dupes)}"


class TestGuardMismatches:
    def _get_mismatches(self, results):
        return results["defects"]["guard_mismatches"]

    def test_ccprmprqi002_number_mismatch(self, results):
        """runCCPRMPRQI002 executes I_003 instead of expected I_002."""
        for m in self._get_mismatches(results):
            if (m["guard_function"] == "runCCPRMPRQI002" and
                    "I_003" in m["executed_testcase"]):
                return
        pytest.fail(
            "Expected mismatch: runCCPRMPRQI002 -> SIP_CC_PR_MP_RQ_I_003"
        )

    def test_ccprmprqi003_number_mismatch(self, results):
        """runCCPRMPRQI003 executes I_004 instead of expected I_003."""
        for m in self._get_mismatches(results):
            if (m["guard_function"] == "runCCPRMPRQI003" and
                    "I_004" in m["executed_testcase"]):
                return
        pytest.fail(
            "Expected mismatch: runCCPRMPRQI003 -> SIP_CC_PR_MP_RQ_I_004"
        )

    def test_mgpri001_behavior_mismatch(self, results):
        """runMGPRI001 executes V_016 instead of expected I_001 (type mismatch)."""
        for m in self._get_mismatches(results):
            if (m["guard_function"] == "runMGPRI001" and
                    "V_016" in m["executed_testcase"]):
                return
        pytest.fail(
            "Expected behavior mismatch: runMGPRI001 -> SIP_MG_PR_V_016"
        )

    def test_mgpri002_number_mismatch(self, results):
        """runMGPRI002 executes I_001 instead of expected I_002."""
        for m in self._get_mismatches(results):
            if (m["guard_function"] == "runMGPRI002" and
                    "I_001" in m["executed_testcase"]):
                return
        pytest.fail(
            "Expected mismatch: runMGPRI002 -> SIP_MG_PR_I_001"
        )

    def test_cross_group_mismatch(self, results):
        """runCCPRMPRSV003 executes TR_CL_V_003 instead of MP_RS_V_003."""
        for m in self._get_mismatches(results):
            if (m["guard_function"] == "runCCPRMPRSV003" and
                    "TR_CL" in m["executed_testcase"]):
                assert m["defect_type"] == "cross_group_mismatch", (
                    f"Expected cross_group_mismatch, got {m['defect_type']}"
                )
                return
        pytest.fail(
            "Expected cross-group mismatch: runCCPRMPRSV003 -> "
            "SIP_CC_PR_TR_CL_V_003"
        )

    def test_mismatch_count_minimum(self, results):
        mismatches = self._get_mismatches(results)
        assert len(mismatches) >= 6, (
            f"Expected >= 6 guard mismatches, got {len(mismatches)}"
        )

    def test_mismatch_entry_structure(self, results):
        for m in self._get_mismatches(results):
            assert "guard_function" in m
            assert "executed_testcase" in m
            assert "expected_testcase" in m
            assert "defect_type" in m
            assert m["defect_type"] in {
                "number_mismatch",
                "behavior_type_mismatch",
                "cross_group_mismatch",
            }


class TestTotalDefects:
    def test_total_defect_count(self, results):
        defects = results["defects"]
        total = len(defects["guard_mismatches"]) + len(
            defects["duplicate_guards"]
        )
        assert total >= 8, f"Expected >= 8 total defects, got {total}"

    def test_total_defect_count_field(self, results):
        defects = results["defects"]
        expected = len(defects["guard_mismatches"]) + len(
            defects["duplicate_guards"]
        )
        assert defects["total_defect_count"] == expected


class TestRFCCoverage:
    def test_coverage_not_empty(self, results):
        assert len(results["rfc_coverage"]) > 0

    def test_section_10_2_exists(self, results):
        cov = results["rfc_coverage"]
        assert "10.2" in cov, "Expected RFC section 10.2 in coverage"

    def test_section_10_2_includes_rg_rt_v_001(self, results):
        cov = results["rfc_coverage"]
        assert "SIP_RG_RT_V_001" in cov.get("10.2", []), (
            "SIP_RG_RT_V_001 should be mapped to section 10.2"
        )

    def test_section_8_1_1_exists(self, results):
        cov = results["rfc_coverage"]
        assert "8.1.1" in cov, "Expected RFC section 8.1.1 in coverage"

    def test_section_8_1_1_includes_cc_oe_ce_v_001(self, results):
        cov = results["rfc_coverage"]
        assert "SIP_CC_OE_CE_V_001" in cov.get("8.1.1", []), (
            "SIP_CC_OE_CE_V_001 should be mapped to section 8.1.1"
        )

    def test_multiple_sections_covered(self, results):
        cov = results["rfc_coverage"]
        assert len(cov) >= 5, (
            f"Expected >= 5 RFC sections in coverage, got {len(cov)}"
        )

    def test_coverage_values_are_sorted_lists(self, results):
        for section, testcases in results["rfc_coverage"].items():
            assert isinstance(testcases, list), (
                f"Coverage for {section} should be a list"
            )
            assert testcases == sorted(testcases), (
                f"Testcase list for {section} should be sorted"
            )
