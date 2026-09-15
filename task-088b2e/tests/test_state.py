
"""Verification tests for the TTCN-3 conformance testing pipeline.

Tests verify that:
- The template matching oracle passes (all matcher bugs fixed)
- The conformance engine produces correct reports for both PICS profiles
- PICS filtering, alt-block semantics, template resolution, and verdict
  aggregation all work correctly
"""

import json
import os
import subprocess
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def oracle_result():
    """Run the template matching oracle."""
    return subprocess.run(
        ["python3", "/app/conformance_runner.py"],
        capture_output=True, text=True, cwd="/app", timeout=60
    )


@pytest.fixture(scope="session")
def engine_result():
    """Run the conformance engine to produce report files."""
    return subprocess.run(
        ["python3", "/app/run_conformance.py"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )


def _require_engine(engine_result):
    """Assert the engine ran successfully."""
    if engine_result.returncode != 0:
        pytest.fail(
            f"run_conformance.py failed (exit {engine_result.returncode}):\n"
            f"stdout: {engine_result.stdout}\nstderr: {engine_result.stderr}"
        )


def _load_report(profile):
    path = f"/app/report_{profile}.json"
    assert os.path.exists(path), f"Report file {path} not found"
    with open(path) as f:
        return json.load(f)


def _get_suite(report, name_fragment):
    for s in report["suites"]:
        if name_fragment in s["suite_name"]:
            return s
    raise AssertionError(f"Suite containing '{name_fragment}' not found in report")


def _verdict_map(suite):
    return {r["id"]: r["verdict"] for r in suite["results"]}


# ===================================================================
# Oracle Tests — Template Matching and Verdict Resolution
# ===================================================================

class TestOraclePass:

    def test_oracle_all_pass(self, oracle_result):
        """All template matching and verdict oracle tests must pass."""
        assert oracle_result.returncode == 0, (
            f"Oracle tests failed:\n{oracle_result.stdout}\n{oracle_result.stderr}"
        )

    def test_oracle_reports_13_tests(self, oracle_result):
        """Oracle must find and run all 13 test cases (9 matcher + 4 verdict)."""
        assert "13 total, 13 passed" in oracle_result.stdout, (
            f"Expected 13 tests passed, got:\n{oracle_result.stdout}"
        )


# ===================================================================
# Profile A Report Structure
# ===================================================================

class TestProfileAStructure:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)
        self.report = _load_report("profile_a")

    def test_profile_name(self):
        assert self.report["profile"] == "profile_a"

    def test_has_two_suites(self):
        assert len(self.report["suites"]) == 2

    def test_overall_verdict(self):
        assert self.report["overall_verdict"] == "fail"


# ===================================================================
# Profile A -- SIP Suite
# ===================================================================

class TestProfileASIP:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)
        self.suite = _get_suite(_load_report("profile_a"), "SIP")

    def test_total_test_cases(self):
        assert self.suite["total"] == 7

    def test_selected_count(self):
        assert self.suite["selected"] == 5

    def test_skipped_v002(self):
        assert "SIP_RG_V_002" in self.suite["skipped"]

    def test_skipped_v006(self):
        assert "SIP_RG_V_006" in self.suite["skipped"]

    def test_verdict_v001(self):
        assert _verdict_map(self.suite)["SIP_RG_V_001"] == "pass"

    def test_verdict_v003(self):
        assert _verdict_map(self.suite)["SIP_RG_V_003"] == "pass"

    def test_verdict_i001(self):
        assert _verdict_map(self.suite)["SIP_RG_I_001"] == "inconc"

    def test_verdict_i002(self):
        assert _verdict_map(self.suite)["SIP_RG_I_002"] == "fail"

    def test_verdict_v005(self):
        assert _verdict_map(self.suite)["SIP_RG_V_005"] == "pass"

    def test_suite_verdict(self):
        assert self.suite["suite_verdict"] == "fail"


# ===================================================================
# Profile A -- Diameter Suite
# ===================================================================

class TestProfileADiameter:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)
        self.suite = _get_suite(_load_report("profile_a"), "Diameter")

    def test_total_test_cases(self):
        assert self.suite["total"] == 6

    def test_selected_count(self):
        assert self.suite["selected"] == 5

    def test_skipped_ips02(self):
        assert "TC_AF_IPS_02" in self.suite["skipped"]

    def test_verdict_ips01(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_01"] == "pass"

    def test_verdict_str01(self):
        assert _verdict_map(self.suite)["TC_AF_STR_01"] == "pass"

    def test_verdict_ips03(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_03"] == "inconc"

    def test_verdict_ips04(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_04"] == "pass"

    def test_verdict_leg01(self):
        assert _verdict_map(self.suite)["TC_AF_LEG_01"] == "pass"

    def test_suite_verdict(self):
        assert self.suite["suite_verdict"] == "inconc"


# ===================================================================
# Profile B Report Structure
# ===================================================================

class TestProfileBStructure:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)
        self.report = _load_report("profile_b")

    def test_profile_name(self):
        assert self.report["profile"] == "profile_b"

    def test_overall_verdict(self):
        assert self.report["overall_verdict"] == "fail"


# ===================================================================
# Profile B -- SIP Suite
# ===================================================================

class TestProfileBSIP:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)
        self.suite = _get_suite(_load_report("profile_b"), "SIP")

    def test_all_selected(self):
        assert self.suite["selected"] == 7

    def test_none_skipped(self):
        assert len(self.suite["skipped"]) == 0

    def test_verdict_v001(self):
        assert _verdict_map(self.suite)["SIP_RG_V_001"] == "pass"

    def test_verdict_v002(self):
        assert _verdict_map(self.suite)["SIP_RG_V_002"] == "pass"

    def test_verdict_v003(self):
        assert _verdict_map(self.suite)["SIP_RG_V_003"] == "pass"

    def test_verdict_i001(self):
        assert _verdict_map(self.suite)["SIP_RG_I_001"] == "inconc"

    def test_verdict_i002(self):
        assert _verdict_map(self.suite)["SIP_RG_I_002"] == "fail"

    def test_verdict_v005(self):
        assert _verdict_map(self.suite)["SIP_RG_V_005"] == "pass"

    def test_verdict_v006(self):
        assert _verdict_map(self.suite)["SIP_RG_V_006"] == "pass"

    def test_suite_verdict(self):
        assert self.suite["suite_verdict"] == "fail"


# ===================================================================
# Profile B -- Diameter Suite
# ===================================================================

class TestProfileBDiameter:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)
        self.suite = _get_suite(_load_report("profile_b"), "Diameter")

    def test_selected_count(self):
        assert self.suite["selected"] == 5

    def test_skipped_leg01(self):
        assert "TC_AF_LEG_01" in self.suite["skipped"]

    def test_verdict_ips01(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_01"] == "pass"

    def test_verdict_ips02(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_02"] == "pass"

    def test_verdict_str01(self):
        assert _verdict_map(self.suite)["TC_AF_STR_01"] == "pass"

    def test_verdict_ips03(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_03"] == "inconc"

    def test_verdict_ips04(self):
        assert _verdict_map(self.suite)["TC_AF_IPS_04"] == "pass"

    def test_suite_verdict(self):
        assert self.suite["suite_verdict"] == "inconc"


# ===================================================================
# PICS Filtering -- cross-profile verification
# ===================================================================

class TestPICSFiltering:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)

    def test_or_expression_selects_v003_for_both(self):
        """SIP_RG_V_003 uses (PICS_DEREG OR PICS_ADMIN_DEREG) -- selected for both."""
        for profile in ("profile_a", "profile_b"):
            suite = _get_suite(_load_report(profile), "SIP")
            ids = {r["id"] for r in suite["results"]}
            assert "SIP_RG_V_003" in ids, f"V_003 missing in {profile}"

    def test_not_expression_asymmetry(self):
        """TC_AF_LEG_01 uses NOT PICS_LEGACY_MODE: selected A, skipped B."""
        a = _get_suite(_load_report("profile_a"), "Diameter")
        b = _get_suite(_load_report("profile_b"), "Diameter")
        assert "TC_AF_LEG_01" in {r["id"] for r in a["results"]}
        assert "TC_AF_LEG_01" not in {r["id"] for r in b["results"]}

    def test_and_chain_filters_auth(self):
        """SIP_RG_V_002 requires PICS_AUTH: skipped A, selected B."""
        a = _get_suite(_load_report("profile_a"), "SIP")
        b = _get_suite(_load_report("profile_b"), "SIP")
        assert "SIP_RG_V_002" in a["skipped"]
        assert "SIP_RG_V_002" in {r["id"] for r in b["results"]}


# ===================================================================
# Alt-block and Repeat Semantics
# ===================================================================

class TestAltSemantics:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)

    def test_first_match_ordering(self):
        """SIP_RG_I_002: 400 template doesn't match 200, 2xx template does -> fail."""
        suite = _get_suite(_load_report("profile_a"), "SIP")
        assert _verdict_map(suite)["SIP_RG_I_002"] == "fail"

    def test_error_template_ordering(self):
        """TC_AF_IPS_04: success template doesn't match 5012, error template does -> pass."""
        suite = _get_suite(_load_report("profile_a"), "Diameter")
        assert _verdict_map(suite)["TC_AF_IPS_04"] == "pass"

    def test_repeat_advances_response_queue(self):
        """SIP_RG_V_005: 100 Trying -> repeat -> 200 OK -> pass."""
        suite = _get_suite(_load_report("profile_a"), "SIP")
        assert _verdict_map(suite)["SIP_RG_V_005"] == "pass"

    def test_nested_alt_auth_exchange(self):
        """SIP_RG_V_002: 401 -> resend with auth -> 200 OK -> pass (nested alt)."""
        suite = _get_suite(_load_report("profile_b"), "SIP")
        assert _verdict_map(suite)["SIP_RG_V_002"] == "pass"

    def test_timeout_produces_inconc(self):
        """SIP_RG_I_001 and TC_AF_IPS_03: null SUT response -> timeout -> inconc."""
        sip = _get_suite(_load_report("profile_a"), "SIP")
        dia = _get_suite(_load_report("profile_a"), "Diameter")
        assert _verdict_map(sip)["SIP_RG_I_001"] == "inconc"
        assert _verdict_map(dia)["TC_AF_IPS_03"] == "inconc"


# ===================================================================
# Template Modifies Resolution
# ===================================================================

class TestTemplateModifies:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)

    def test_modifies_200_ok(self):
        """response_200_ok_tmpl modifies response_2xx_tmpl -> matches 200 responses."""
        suite = _get_suite(_load_report("profile_a"), "SIP")
        assert _verdict_map(suite)["SIP_RG_V_001"] == "pass"

    def test_modifies_media_template(self):
        """aaa_success_media_tmpl modifies aaa_2xx_base_tmpl -> matches media responses."""
        suite = _get_suite(_load_report("profile_b"), "Diameter")
        assert _verdict_map(suite)["TC_AF_IPS_02"] == "pass"


# ===================================================================
# Multi-Component Verdict Aggregation
# ===================================================================

class TestMultiComponent:

    @pytest.fixture(autouse=True)
    def setup(self, engine_result):
        _require_engine(engine_result)

    def test_two_ptc_both_pass(self):
        """SIP_RG_V_006: mtc=pass, ua2=pass -> test verdict=pass."""
        suite = _get_suite(_load_report("profile_b"), "SIP")
        assert _verdict_map(suite)["SIP_RG_V_006"] == "pass"
