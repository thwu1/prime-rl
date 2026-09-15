
import json
import os
import pytest

EXPECTED_RESULTS = {
    "patient_001": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": True},
    "patient_002": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": False},
    "patient_003": {"IPP": False, "DENOM": False, "DENEX": False, "NUMER": False},
    "patient_004": {"IPP": False, "DENOM": False, "DENEX": False, "NUMER": False},
    "patient_005": {"IPP": False, "DENOM": False, "DENEX": False, "NUMER": False},
    "patient_006": {"IPP": False, "DENOM": False, "DENEX": False, "NUMER": False},
    "patient_007": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": False},
    "patient_008": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": True},
    "patient_009": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": False},
    "patient_010": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": False},
    "patient_011": {"IPP": True, "DENOM": True, "DENEX": True, "NUMER": False},
    "patient_012": {"IPP": True, "DENOM": True, "DENEX": True, "NUMER": False},
    "patient_013": {"IPP": True, "DENOM": True, "DENEX": True, "NUMER": False},
    "patient_014": {"IPP": True, "DENOM": True, "DENEX": True, "NUMER": False},
    "patient_015": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": True},
    "patient_016": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": False},
    "patient_017": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": True},
    "patient_018": {"IPP": True, "DENOM": True, "DENEX": True, "NUMER": False},
    "patient_019": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": True},
    "patient_020": {"IPP": True, "DENOM": True, "DENEX": False, "NUMER": False},
}


def load_results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}. "
        "The evaluator must write population results to /app/results.json"
    )
    with open(results_path) as f:
        return json.load(f)


class TestResultsFileExists:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json must exist at /app/results.json"

    def test_results_is_valid_json(self):
        results = load_results()
        assert isinstance(results, dict), "results.json must contain a JSON object"

    def test_all_patients_present(self):
        results = load_results()
        for patient_id in EXPECTED_RESULTS:
            assert patient_id in results, (
                f"Missing patient {patient_id} in results.json. "
                f"Expected all 20 patients to be evaluated."
            )

    def test_result_structure(self):
        results = load_results()
        for patient_id, result in results.items():
            if patient_id in EXPECTED_RESULTS:
                for field in ["IPP", "DENOM", "DENEX", "NUMER"]:
                    assert field in result, (
                        f"Patient {patient_id}: missing field '{field}'. "
                        f"Each patient result must have IPP, DENOM, DENEX, NUMER."
                    )
                    assert isinstance(result[field], bool), (
                        f"Patient {patient_id}: field '{field}' must be boolean, "
                        f"got {type(result[field]).__name__}"
                    )


class TestIPPCriteria:
    """Test Initial Population membership."""

    def test_patient_001_ipp_pass(self):
        results = load_results()
        assert results["patient_001"]["IPP"] is True

    def test_patient_003_too_young(self):
        results = load_results()
        assert results["patient_003"]["IPP"] is False

    def test_patient_004_too_old(self):
        results = load_results()
        assert results["patient_004"]["IPP"] is False

    def test_patient_005_late_htn_onset(self):
        results = load_results()
        assert results["patient_005"]["IPP"] is False

    def test_patient_006_no_qualifying_encounter(self):
        results = load_results()
        assert results["patient_006"]["IPP"] is False

    def test_patient_019_relapse_status_qualifies(self):
        """CQL isActive includes relapse; absent verificationStatus is unspecified."""
        results = load_results()
        assert results["patient_019"]["IPP"] is True


class TestNumerator:
    """Test Numerator (blood pressure) logic."""

    def test_patient_001_bp_pass(self):
        results = load_results()
        assert results["patient_001"]["NUMER"] is True

    def test_patient_002_high_bp(self):
        results = load_results()
        assert results["patient_002"]["NUMER"] is False

    def test_patient_007_bp_from_ed(self):
        results = load_results()
        assert results["patient_007"]["IPP"] is True
        assert results["patient_007"]["NUMER"] is False

    def test_patient_008_multiple_bps_lowest(self):
        results = load_results()
        assert results["patient_008"]["NUMER"] is True

    def test_patient_009_sbp_boundary(self):
        results = load_results()
        assert results["patient_009"]["NUMER"] is False

    def test_patient_010_dbp_boundary(self):
        results = load_results()
        assert results["patient_010"]["NUMER"] is False

    def test_patient_015_incomplete_recent_bp(self):
        results = load_results()
        assert results["patient_015"]["IPP"] is True
        assert results["patient_015"]["NUMER"] is True

    def test_patient_016_preliminary_status_not_qualifying(self):
        """Observation status 'preliminary' is not in {final, amended, corrected}."""
        results = load_results()
        assert results["patient_016"]["IPP"] is True
        assert results["patient_016"]["NUMER"] is False

    def test_patient_019_relapse_htn_with_good_bp(self):
        """Relapse HTN + good BP → NUMER true."""
        results = load_results()
        assert results["patient_019"]["NUMER"] is True

    def test_patient_020_encounter_class_disqualification(self):
        """BP references encounter with class IMP → disqualified even if encounter
        type is not in Inpatient/ED value sets."""
        results = load_results()
        assert results["patient_020"]["IPP"] is True
        assert results["patient_020"]["NUMER"] is False


class TestDenominatorExclusions:
    """Test Denominator Exclusion criteria."""

    def test_patient_011_pregnancy(self):
        results = load_results()
        assert results["patient_011"]["DENEX"] is True
        assert results["patient_011"]["NUMER"] is False

    def test_patient_012_esrd_procedure(self):
        results = load_results()
        assert results["patient_012"]["DENEX"] is True
        assert results["patient_012"]["NUMER"] is False

    def test_patient_013_hospice(self):
        results = load_results()
        assert results["patient_013"]["DENEX"] is True
        assert results["patient_013"]["NUMER"] is False

    def test_patient_014_frailty_age_82(self):
        """Age >= 81 with frailty only → DENEX true."""
        results = load_results()
        assert results["patient_014"]["DENEX"] is True
        assert results["patient_014"]["NUMER"] is False

    def test_patient_017_age_80_frailty_only_not_excluded(self):
        """Age 80 (in [66,80]) with frailty but NO advanced illness → NOT excluded.
        The 66-80 tier requires BOTH frailty AND advanced illness."""
        results = load_results()
        assert results["patient_017"]["IPP"] is True
        assert results["patient_017"]["DENEX"] is False
        assert results["patient_017"]["NUMER"] is True

    def test_patient_018_age_67_frailty_and_advanced_illness(self):
        """Age 67 (in [66,80]) with BOTH frailty AND advanced illness → DENEX true."""
        results = load_results()
        assert results["patient_018"]["DENEX"] is True
        assert results["patient_018"]["NUMER"] is False


class TestPopulationFlow:
    """Test overall population flow semantics."""

    def test_ipp_false_means_all_false(self):
        """When IPP is false, all other populations must be false."""
        results = load_results()
        for pid in ["patient_003", "patient_004", "patient_005", "patient_006"]:
            r = results[pid]
            assert r["IPP"] is False, f"{pid}: IPP should be False"
            assert r["DENOM"] is False, f"{pid}: DENOM should be False when IPP is False"
            assert r["DENEX"] is False, f"{pid}: DENEX should be False when IPP is False"
            assert r["NUMER"] is False, f"{pid}: NUMER should be False when IPP is False"

    def test_denex_true_means_numer_false(self):
        """When DENEX is true, NUMER must be false."""
        results = load_results()
        for pid in ["patient_011", "patient_012", "patient_013", "patient_014", "patient_018"]:
            r = results[pid]
            assert r["DENEX"] is True, f"{pid}: DENEX should be True"
            assert r["NUMER"] is False, f"{pid}: NUMER must be False when DENEX is True"

    def test_complete_evaluation(self):
        """Verify all 20 patients match expected results exactly."""
        results = load_results()
        for patient_id, expected in EXPECTED_RESULTS.items():
            actual = results[patient_id]
            for field in ["IPP", "DENOM", "DENEX", "NUMER"]:
                assert actual[field] == expected[field], (
                    f"Patient {patient_id}: {field} expected {expected[field]}, "
                    f"got {actual[field]}"
                )
