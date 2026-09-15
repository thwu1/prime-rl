
import json
import os
import pytest


RESULTS_PATH = "/app/output/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Output file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestOutputStructure:
    def test_required_keys_present(self, results):
        required = [
            "cci_per_admission",
            "cci_age_adjusted",
            "sofa_lab_components",
            "suspected_sepsis",
            "nephrotoxic_aki_risk",
            "risk_matrix",
        ]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_cci_has_129_admissions(self, results):
        assert len(results["cci_per_admission"]) == 129

    def test_cci_age_adjusted_has_129_admissions(self, results):
        assert len(results["cci_age_adjusted"]) == 129

    def test_sofa_has_136_icu_stays(self, results):
        assert len(results["sofa_lab_components"]) == 136

    def test_suspected_sepsis_has_136_icu_stays(self, results):
        assert len(results["suspected_sepsis"]) == 136

    def test_risk_matrix_structure(self, results):
        expected_cci_brackets = {"0-2", "3-5", "6+"}
        expected_sofa_brackets = {"0", "1-2", "3+"}
        assert set(results["risk_matrix"].keys()) == expected_cci_brackets
        for bracket in expected_cci_brackets:
            assert set(results["risk_matrix"][bracket].keys()) == expected_sofa_brackets


class TestCharlsonCCI:
    """Verify CCI computation for specific admissions spanning the difficulty range."""

    EXPECTED_CCI = {
        # hadm_id: (cci_no_age, cci_age_adjusted)
        "142345": (4, 6),
        "105331": (1, 1),
        "178513": (11, 14),
        "174997": (10, 13),
        "167021": (8, 9),
        "100375": (1, 5),
        "199207": (2, 5),
        "165520": (3, 7),
    }

    @pytest.mark.parametrize("hadm_id,expected", list(EXPECTED_CCI.items()))
    def test_specific_cci_values(self, results, hadm_id, expected):
        cci_no_age, cci_age_adj = expected
        actual_cci = results["cci_per_admission"][hadm_id]
        assert actual_cci == cci_no_age, (
            f"hadm_id={hadm_id}: expected CCI={cci_no_age}, got {actual_cci}"
        )
        actual_adj = results["cci_age_adjusted"][hadm_id]
        assert actual_adj == cci_age_adj, (
            f"hadm_id={hadm_id}: expected age-adjusted CCI={cci_age_adj}, got {actual_adj}"
        )

    def test_aggregate_cci_sum(self, results):
        total_cci = sum(results["cci_per_admission"].values())
        assert total_cci == 433, f"Expected total CCI sum=433, got {total_cci}"

    def test_aggregate_cci_age_adjusted_sum(self, results):
        total_adj = sum(results["cci_age_adjusted"].values())
        assert total_adj == 758, f"Expected total age-adjusted CCI sum=758, got {total_adj}"

    def test_cci_values_are_integers(self, results):
        for hadm_id, val in results["cci_per_admission"].items():
            assert isinstance(val, int), f"CCI for {hadm_id} is {type(val)}, expected int"

    def test_age_deidentification_handled(self, results):
        """hadm_id 107689 (subject 41983) has deidentified age.
        CCI without age is 2, so age-adjusted should be 2 + 4 = 6."""
        assert results["cci_age_adjusted"]["107689"] == 6


class TestSOFALabComponents:
    """Verify SOFA lab-based organ dysfunction scoring."""

    EXPECTED_SOFA = {
        # icustay_id: (renal, hepatic, coagulation, partial_sofa)
        "228977": (4, 4, 3, 11),  # highest partial SOFA: creat 6.4, bili 12.8, plt 38
        "248755": (3, 2, 3, 8),   # creat 4.3, bili 3.7, plt 49
        "203766": (1, 2, 4, 7),   # creat 1.8, bili 2.3, plt 16
        "226055": (3, 2, 2, 7),   # creat 4.5, bili 2.8, plt 88
        "223177": (2, 2, 2, 6),   # creat 2.5, bili 2.9, plt 58
        "206504": (4, 0, 1, 5),   # creat 5.3, no bili data, plt 106
    }

    @pytest.mark.parametrize("icustay_id,expected", list(EXPECTED_SOFA.items()))
    def test_specific_sofa_components(self, results, icustay_id, expected):
        r_exp, h_exp, c_exp, ps_exp = expected
        actual = results["sofa_lab_components"][icustay_id]
        assert actual["renal"] == r_exp, (
            f"ICU {icustay_id}: expected renal={r_exp}, got {actual['renal']}"
        )
        assert actual["hepatic"] == h_exp, (
            f"ICU {icustay_id}: expected hepatic={h_exp}, got {actual['hepatic']}"
        )
        assert actual["coagulation"] == c_exp, (
            f"ICU {icustay_id}: expected coagulation={c_exp}, got {actual['coagulation']}"
        )
        assert actual["partial_sofa"] == ps_exp, (
            f"ICU {icustay_id}: expected partial_sofa={ps_exp}, got {actual['partial_sofa']}"
        )

    def test_aggregate_partial_sofa_sum(self, results):
        total = sum(v["partial_sofa"] for v in results["sofa_lab_components"].values())
        assert total == 80, f"Expected total partial SOFA sum=80, got {total}"

    def test_icu_stays_with_dysfunction(self, results):
        count = sum(
            1 for v in results["sofa_lab_components"].values()
            if v["partial_sofa"] > 0
        )
        assert count == 21, f"Expected 21 ICU stays with organ dysfunction, got {count}"

    def test_sofa_components_are_integers(self, results):
        for icuid, comp in results["sofa_lab_components"].items():
            for key in ["renal", "hepatic", "coagulation", "partial_sofa"]:
                assert isinstance(comp[key], int), (
                    f"ICU {icuid} {key} is {type(comp[key])}, expected int"
                )

    def test_zero_sofa_for_no_lab_data(self, results):
        """ICU stays with no lab data should have all zeros."""
        # ICU 201204 (subject 42321) has no lab data during ICU stay
        actual = results["sofa_lab_components"]["201204"]
        assert actual["partial_sofa"] == 0


class TestSuspectedSepsis:
    """Verify sepsis screening: partial SOFA >= 2 AND systemic antimicrobials."""

    def test_sepsis_count(self, results):
        count = sum(1 for v in results["suspected_sepsis"].values() if v)
        assert count == 12, f"Expected 12 suspected sepsis ICU stays, got {count}"

    def test_specific_sepsis_cases(self, results):
        expected_true = [
            "201006", "203766", "206504", "215460", "223177",
            "226055", "228977", "235482", "248755", "258147",
            "267090", "286020",
        ]
        actual_true = sorted(
            [k for k, v in results["suspected_sepsis"].items() if v],
            key=int,
        )
        assert actual_true == expected_true, (
            f"Sepsis ICU stays mismatch.\n"
            f"Expected: {expected_true}\n"
            f"Got: {actual_true}"
        )

    def test_non_sepsis_cases(self, results):
        """ICU stays with antibiotics but low SOFA should not be flagged."""
        # ICU 204881: has antibiotics but partial SOFA = 0
        assert results["suspected_sepsis"]["204881"] is False
        # ICU 201204: no antibiotics, no lab data
        assert results["suspected_sepsis"]["201204"] is False


class TestNephrotoxicAKIRisk:
    EXPECTED_SUBJECTS = [
        10006, 10029, 10032, 10038, 10040, 10044,
        10045, 10059, 10061, 10076,
    ]

    def test_nephrotoxic_risk_count(self, results):
        assert len(results["nephrotoxic_aki_risk"]) == 10

    def test_nephrotoxic_risk_exact_list(self, results):
        actual = sorted(results["nephrotoxic_aki_risk"])
        assert actual == self.EXPECTED_SUBJECTS, (
            f"Nephrotoxic AKI risk mismatch.\n"
            f"Expected: {self.EXPECTED_SUBJECTS}\n"
            f"Got: {actual}"
        )


class TestRiskMatrix:
    EXPECTED_RATES = {
        ("0-2", "0"): 0.5,
        ("0-2", "1-2"): 1.0,
        ("0-2", "3+"): 1.0,
        ("3-5", "0"): 0.1707,
        ("3-5", "1-2"): 0.0,
        ("3-5", "3+"): 0.3333,
        ("6+", "0"): 0.4194,
        ("6+", "1-2"): 0.25,
        ("6+", "3+"): 0.375,
    }

    @pytest.mark.parametrize(
        "brackets,expected_rate",
        list(EXPECTED_RATES.items()),
    )
    def test_risk_matrix_rates(self, results, brackets, expected_rate):
        cci_b, sofa_b = brackets
        actual = results["risk_matrix"][cci_b][sofa_b]
        assert abs(actual - expected_rate) < 0.0002, (
            f"CCI {cci_b} x SOFA {sofa_b}: expected {expected_rate}, got {actual}"
        )
