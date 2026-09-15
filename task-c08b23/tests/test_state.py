
import json
import os
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def alpha_report():
    path = "/app/output/alpha_report.json"
    assert os.path.exists(path), "alpha_report.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def beta_report():
    path = "/app/output/beta_report.json"
    assert os.path.exists(path), "beta_report.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def comparison():
    path = "/app/output/comparison.json"
    assert os.path.exists(path), "comparison.json not found"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_category(report, vul_class, cat_key):
    return report["vulnerability_classes"][vul_class][cat_key]


def get_cwe(report, vul_class, cat_key, cwe_id):
    cat = get_category(report, vul_class, cat_key)
    return cat["cwe_scores"][cwe_id]


# ===========================================================================
# ALPHA REPORT TESTS
# ===========================================================================

class TestAlphaStructure:
    def test_has_besspin_scale(self, alpha_report):
        assert "besspin_scale" in alpha_report
        assert isinstance(alpha_report["besspin_scale"], (int, float))

    def test_has_naive_tally(self, alpha_report):
        tally = alpha_report["naive_tally"]
        for key in ("binary_percentage", "exact_percentage", "total_cwes", "binary_pass_count"):
            assert key in tally

    def test_has_all_vulnerability_classes(self, alpha_report):
        vc = alpha_report["vulnerability_classes"]
        for cls in ["bufferErrors", "PPAC", "resourceManagement",
                     "informationLeakage", "numericErrors", "hardwareSoC", "injection"]:
            assert cls in vc, f"Missing vulnerability class: {cls}"


class TestAlphaScale:
    def test_besspin_scale_value(self, alpha_report):
        assert abs(alpha_report["besspin_scale"] - 30.7312) < 0.05


class TestAlphaNaiveTally:
    def test_total_cwes(self, alpha_report):
        assert alpha_report["naive_tally"]["total_cwes"] == 26

    def test_binary_pass_count(self, alpha_report):
        assert alpha_report["naive_tally"]["binary_pass_count"] == 6

    def test_binary_percentage(self, alpha_report):
        assert abs(alpha_report["naive_tally"]["binary_percentage"] - 23.0769) < 0.01

    def test_exact_percentage(self, alpha_report):
        assert abs(alpha_report["naive_tally"]["exact_percentage"] - 35.8974) < 0.05


# ---------------------------------------------------------------------------
# Alpha CWE-level: DETECTED aliasing (Bug 1 verification)
# ---------------------------------------------------------------------------

class TestAlphaDetectedAliasing:
    def test_cwe_212_detected_value(self, alpha_report):
        """DETECTED effective value must be 3 (aliased to NONE), NOT 4."""
        cwe = get_cwe(alpha_report, "informationLeakage", "IS", "212")
        assert cwe["floor_score"] == "DETECTED"
        assert abs(cwe["exact_value"] - 3.0) < 1e-6

    def test_cwe_120_none_detected_avg(self, alpha_report):
        """NONE(3) + DETECTED(3) must average to 3.0, not 3.5."""
        cwe = get_cwe(alpha_report, "bufferErrors", "BE", "120")
        assert cwe["floor_score"] == "NONE"
        assert abs(cwe["exact_value"] - 3.0) < 1e-6
        assert abs(cwe["normalized"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Alpha CWE-level: single-part scores
# ---------------------------------------------------------------------------

class TestAlphaSinglePartCWEs:
    def test_cwe_118_high(self, alpha_report):
        cwe = get_cwe(alpha_report, "bufferErrors", "BE", "118")
        assert cwe["floor_score"] == "HIGH"
        assert abs(cwe["normalized"] - 0.0) < 1e-6

    def test_cwe_119_med(self, alpha_report):
        cwe = get_cwe(alpha_report, "bufferErrors", "BE", "119")
        assert cwe["floor_score"] == "MED"
        assert abs(cwe["normalized"] - 1 / 3) < 1e-4

    def test_cwe_122_low(self, alpha_report):
        cwe = get_cwe(alpha_report, "bufferErrors", "BE", "122")
        assert cwe["floor_score"] == "LOW"
        assert abs(cwe["normalized"] - 2 / 3) < 1e-4

    def test_cwe_369_none(self, alpha_report):
        cwe = get_cwe(alpha_report, "numericErrors", "RDE", "369")
        assert cwe["floor_score"] == "NONE"
        assert abs(cwe["normalized"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Alpha CWE-level: multi-part aggregation with floor division (Bug 5)
# ---------------------------------------------------------------------------

class TestAlphaMultiPartCWEs:
    def test_cwe_787_med_none(self, alpha_report):
        """MED(1) + NONE(3) -> exact=2.0, floor=LOW."""
        cwe = get_cwe(alpha_report, "bufferErrors", "BE", "787")
        assert cwe["floor_score"] == "LOW"
        assert abs(cwe["exact_value"] - 2.0) < 1e-6

    def test_cwe_416_med_high(self, alpha_report):
        """MED(1) + HIGH(0) -> exact=0.5, floor=HIGH (floor(0.5)=0, NOT round)."""
        cwe = get_cwe(alpha_report, "resourceManagement", "RC", "416")
        assert cwe["floor_score"] == "HIGH"
        assert abs(cwe["exact_value"] - 0.5) < 1e-6
        assert abs(cwe["normalized"] - 1 / 6) < 1e-4


# ---------------------------------------------------------------------------
# Alpha error propagation (Bug 2 - single-part, same for min/max)
# ---------------------------------------------------------------------------

class TestAlphaErrorPropagation:
    def test_cwe_762_call_err(self, alpha_report):
        cwe = get_cwe(alpha_report, "resourceManagement", "MDL", "762")
        assert cwe["floor_score"] == "CALL_ERR"


# ---------------------------------------------------------------------------
# Alpha overlapping CWE membership
# ---------------------------------------------------------------------------

class TestAlphaOverlappingCWEs:
    def test_cwe_415_in_rc_and_pm(self, alpha_report):
        rc_cwe = get_cwe(alpha_report, "resourceManagement", "RC", "415")
        pm_cwe = get_cwe(alpha_report, "resourceManagement", "PM", "415")
        assert abs(rc_cwe["normalized"] - pm_cwe["normalized"]) < 1e-6

    def test_cwe_787_in_be_and_ish(self, alpha_report):
        be_cwe = get_cwe(alpha_report, "bufferErrors", "BE", "787")
        ish_cwe = get_cwe(alpha_report, "bufferErrors", "ISH", "787")
        assert abs(be_cwe["normalized"] - ish_cwe["normalized"]) < 1e-6


# ---------------------------------------------------------------------------
# Alpha category weights (Bug 4 verification)
# ---------------------------------------------------------------------------

class TestAlphaCategoryWeights:
    @pytest.mark.parametrize("vul_class,cat_key,expected_weight", [
        ("bufferErrors", "BE", 1.0),
        ("bufferErrors", "ISH", 1.0),
        ("PPAC", "AUT", 0.9),
        ("PPAC", "ACC", 0.08),
        ("resourceManagement", "MDL", 0.54),
        ("resourceManagement", "RC", 0.9),
        ("resourceManagement", "PM", 1.0),
        ("informationLeakage", "IE", 1.0),
        ("informationLeakage", "OD", 0.48),
        ("informationLeakage", "IS", 1.0),
        ("numericErrors", "RDE", 0.54),
        ("numericErrors", "TE", 0.54),
        ("numericErrors", "VE", 1.0),
        ("injection", "UD", 1.0),
    ])
    def test_weight(self, alpha_report, vul_class, cat_key, expected_weight):
        cat = get_category(alpha_report, vul_class, cat_key)
        assert abs(cat["weight"] - expected_weight) < 1e-4


# ---------------------------------------------------------------------------
# Alpha category scores (Bug 3 verification: N/A exclusion)
# ---------------------------------------------------------------------------

class TestAlphaCategoryScores:
    @pytest.mark.parametrize("vul_class,cat_key,expected_score", [
        ("bufferErrors", "BE", 8 / 21),
        ("bufferErrors", "ISH", 5 / 9),
        ("PPAC", "AUT", 0.5),
        ("PPAC", "ACC", 1.0),
        ("resourceManagement", "MDL", 0.0),
        ("resourceManagement", "RC", 1 / 12),
        ("resourceManagement", "PM", 7 / 24),
        ("informationLeakage", "IE", 1 / 6),
        ("informationLeakage", "OD", 2 / 3),
        ("informationLeakage", "IS", 7 / 12),
        ("numericErrors", "RDE", 1 / 3),
        ("numericErrors", "TE", 1 / 3),
        ("numericErrors", "VE", 0.0),
        ("injection", "UD", 1 / 9),
    ])
    def test_category_score(self, alpha_report, vul_class, cat_key, expected_score):
        cat = get_category(alpha_report, vul_class, cat_key)
        assert cat["normalized_score"] is not None
        assert abs(cat["normalized_score"] - expected_score) < 1e-4


class TestAlphaNotApplicable:
    def test_hardware_soc_null(self, alpha_report):
        cat = get_category(alpha_report, "hardwareSoC", "Selected")
        assert cat["normalized_score"] is None


# ===========================================================================
# BETA REPORT TESTS
# ===========================================================================

class TestBetaScale:
    def test_besspin_scale_value(self, beta_report):
        """Beta should score ~55.65%."""
        assert abs(beta_report["besspin_scale"] - 55.6495) < 0.05


class TestBetaNaiveTally:
    def test_total_cwes(self, beta_report):
        """27 CWEs including 590 (FAIL) and 762 (CALL_ERR), excluding N/A."""
        assert beta_report["naive_tally"]["total_cwes"] == 27

    def test_binary_pass_count(self, beta_report):
        assert beta_report["naive_tally"]["binary_pass_count"] == 6

    def test_binary_percentage(self, beta_report):
        assert abs(beta_report["naive_tally"]["binary_percentage"] - 22.2222) < 0.01

    def test_exact_percentage(self, beta_report):
        assert abs(beta_report["naive_tally"]["exact_percentage"] - 51.4403) < 0.05


# ---------------------------------------------------------------------------
# Beta CWE-level: floor division verification (Bug 5)
# ---------------------------------------------------------------------------

class TestBetaFloorDivision:
    def test_cwe_456_floor_not_round(self, beta_report):
        """MED(1)+MED(1)+HIGH(0) -> exact=2/3, floor(2/3)=0 -> HIGH, NOT round(2/3)=1 -> MED."""
        cwe = get_cwe(beta_report, "numericErrors", "VE", "456")
        assert cwe["floor_score"] == "HIGH", (
            f"CWE-456 floor_score should be HIGH (floor(2/3)=0), got {cwe['floor_score']}"
        )
        assert abs(cwe["exact_value"] - 2 / 3) < 1e-4
        assert abs(cwe["normalized"] - 2 / 9) < 1e-4


# ---------------------------------------------------------------------------
# Beta CWE-level: error propagation verification (Bug 2)
# ---------------------------------------------------------------------------

class TestBetaErrorPropagation:
    def test_cwe_590_fail_not_call_err(self, beta_report):
        """CALL_ERR(-1) + FAIL(-2) -> min -> FAIL (most severe), NOT CALL_ERR."""
        cwe = get_cwe(beta_report, "resourceManagement", "MDL", "590")
        assert cwe["floor_score"] == "FAIL", (
            f"CWE-590 should propagate FAIL (min/most severe error), got {cwe['floor_score']}"
        )


# ---------------------------------------------------------------------------
# Beta CWE-level: multi-part aggregation
# ---------------------------------------------------------------------------

class TestBetaMultiPartCWEs:
    def test_cwe_120_none_low(self, beta_report):
        """NONE(3) + LOW(2) -> exact=2.5, floor=LOW."""
        cwe = get_cwe(beta_report, "bufferErrors", "BE", "120")
        assert cwe["floor_score"] == "LOW"
        assert abs(cwe["exact_value"] - 2.5) < 1e-6
        assert abs(cwe["normalized"] - 5 / 6) < 1e-4

    def test_cwe_416_low_none(self, beta_report):
        """LOW(2) + NONE(3) -> exact=2.5, floor=LOW."""
        cwe = get_cwe(beta_report, "resourceManagement", "RC", "416")
        assert cwe["floor_score"] == "LOW"
        assert abs(cwe["exact_value"] - 2.5) < 1e-6


# ---------------------------------------------------------------------------
# Beta category scores
# ---------------------------------------------------------------------------

class TestBetaCategoryScores:
    @pytest.mark.parametrize("vul_class,cat_key,expected_score", [
        ("bufferErrors", "BE", 4 / 7),
        ("bufferErrors", "ISH", 2 / 3),
        ("PPAC", "AUT", 0.0),
        ("PPAC", "ACC", 1 / 3),
        ("resourceManagement", "MDL", 0.0),
        ("resourceManagement", "RC", 7 / 12),
        ("resourceManagement", "PM", 13 / 24),
        ("informationLeakage", "IE", 5 / 6),
        ("informationLeakage", "OD", 1.0),
        ("informationLeakage", "IS", 11 / 12),
        ("numericErrors", "RDE", 5 / 9),
        ("numericErrors", "TE", 2 / 3),
        ("numericErrors", "VE", 2 / 9),
        ("injection", "UD", 2 / 3),
    ])
    def test_category_score(self, beta_report, vul_class, cat_key, expected_score):
        cat = get_category(beta_report, vul_class, cat_key)
        assert cat["normalized_score"] is not None
        assert abs(cat["normalized_score"] - expected_score) < 1e-4


class TestBetaNotApplicable:
    def test_hardware_soc_null(self, beta_report):
        cat = get_category(beta_report, "hardwareSoC", "Selected")
        assert cat["normalized_score"] is None


# ---------------------------------------------------------------------------
# Beta: verify superseded data was filtered out
# ---------------------------------------------------------------------------

class TestBetaDataFiltering:
    def test_cwe_416_not_both_high(self, beta_report):
        """Superseded run had 416 as HIGH+HIGH. Valid run has LOW+NONE."""
        cwe = get_cwe(beta_report, "resourceManagement", "RC", "416")
        assert cwe["exact_value"] > 0.1, (
            "CWE-416 appears to use superseded (invalid) data"
        )

    def test_injection_inj1_not_none(self, beta_report):
        """Superseded run had INJ_1 as NONE. Valid run has LOW."""
        cwe = get_cwe(beta_report, "injection", "UD", "INJ_1")
        assert cwe["floor_score"] != "NONE", (
            "INJ_1 appears to use superseded (invalid) data"
        )


# ===========================================================================
# COMPARISON TESTS
# ===========================================================================

class TestComparison:
    def test_alpha_scale(self, comparison):
        assert abs(comparison["alpha_besspin_scale"] - 30.7312) < 0.05

    def test_beta_scale(self, comparison):
        assert abs(comparison["beta_besspin_scale"] - 55.6495) < 0.05

    def test_more_secure_processor(self, comparison):
        assert comparison["more_secure_processor"] == "beta"

    def test_alpha_advantages(self, comparison):
        advantages = sorted(comparison["alpha_category_advantages"])
        assert advantages == ["ACC", "AUT"], (
            f"Alpha advantages should be ACC, AUT; got {advantages}"
        )

    def test_beta_advantages(self, comparison):
        advantages = sorted(comparison["beta_category_advantages"])
        expected = ["BE", "IE", "IS", "ISH", "OD", "PM", "RC", "RDE", "TE", "UD", "VE"]
        assert advantages == expected, (
            f"Beta advantages mismatch; got {advantages}"
        )

    def test_highest_impact_category(self, comparison):
        """IE has the largest weight * |beta_score - alpha_score| = 1.0 * |5/6 - 1/6| = 2/3."""
        assert comparison["highest_impact_category"] == "IE"
