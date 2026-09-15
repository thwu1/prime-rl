"""

Tests for Medication Safety Audit.
Verifies eGFR computation, CKD staging, medication actions, alert levels,
and drug-drug interaction detection.
"""

import json
import math
import os
import pytest

REPORT_PATH = "/app/output/renal_dosing_report.json"

# -------------------------------------------------------------------
# Ground truth: patient data and expected results
# -------------------------------------------------------------------

def _ckd_epi_2021(scr_mg_dl, age, is_female):
    """CKD-EPI 2021 race-free equation."""
    if is_female:
        kappa, alpha = 0.7, -0.241
    else:
        kappa, alpha = 0.9, -0.302
    ratio = scr_mg_dl / kappa
    term1 = min(ratio, 1.0) ** alpha
    term2 = max(ratio, 1.0) ** (-1.200)
    term3 = 0.9938 ** age
    egfr = 142.0 * term1 * term2 * term3
    if is_female:
        egfr *= 1.012
    return egfr


# Expected patient data (ground truth from FHIR bundles)
EXPECTED = {
    "pat-001": {
        "name": "Maria Chen",
        "age": 72,
        "sex": "female",
        "scr": 2.1,
        "egfr": _ckd_epi_2021(2.1, 72, True),
        "ckd_stage": "G4",
        "alert_level": "CRITICAL",
        "meds": {
            "metformin":  "STOP",
            "digoxin":    "REDUCE",
            "apixaban":   "REDUCE",
            "lisinopril": "NO_CHANGE",
        },
        "expected_interactions": [("digoxin", "apixaban"), ("metformin", "lisinopril")],
    },
    "pat-002": {
        "name": "James Walker",
        "age": 58,
        "sex": "male",
        "scr": 0.9,
        "egfr": _ckd_epi_2021(0.9, 58, False),
        "ckd_stage": "G1",
        "alert_level": "OK",
        "meds": {
            "atorvastatin": "NO_CHANGE",
            "lisinopril":   "NO_CHANGE",
            "metformin":    "NO_CHANGE",
        },
        "expected_interactions": [("metformin", "lisinopril")],
    },
    "pat-003": {
        "name": "Robert Davis",
        "age": 80,
        "sex": "male",
        "scr": 3.5,
        "egfr": _ckd_epi_2021(3.5, 80, False),
        "ckd_stage": "G4",
        "alert_level": "CRITICAL",
        "meds": {
            "gabapentin":  "REDUCE",
            "allopurinol": "REDUCE",
            "dabigatran":  "REDUCE",
            "metformin":   "STOP",
        },
        "expected_interactions": [("dabigatran", "allopurinol"), ("gabapentin", "dabigatran")],
    },
    "pat-004": {
        "name": "Sarah Johnson",
        "age": 65,
        "sex": "female",
        "scr": 1.4,
        "egfr": _ckd_epi_2021(1.4, 65, True),
        "ckd_stage": "G3b",
        "alert_level": "ADJUST",
        "meds": {
            "rivaroxaban": "REDUCE",
            "amlodipine":  "NO_CHANGE",
            "metformin":   "REDUCE",
        },
        "expected_interactions": [("rivaroxaban", "amlodipine")],
    },
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def load_report():
    assert os.path.exists(REPORT_PATH), (
        f"Output file {REPORT_PATH} not found. "
        "The pipeline must write results to /app/output/renal_dosing_report.json"
    )
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert "patients" in data, "Report JSON must contain a top-level 'patients' array"
    return {p["patient_id"]: p for p in data["patients"]}


def _find_med(meds_list, drug_name):
    """Find a medication entry by generic name (case-insensitive substring)."""
    for m in meds_list:
        name = m.get("drug_name", "").lower()
        if drug_name.lower() in name:
            return m
    return None


def _get_interaction_pairs(interactions):
    """Get set of drug pairs (both orderings) from interactions list."""
    pairs = set()
    for ix in interactions:
        a = ix.get("drug_a", "").lower()
        b = ix.get("drug_b", "").lower()
        pairs.add((a, b))
        pairs.add((b, a))
    return pairs


# -------------------------------------------------------------------
# Tests: Report structure
# -------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists_and_valid_json(self):
        report = load_report()
        assert len(report) == 4, f"Expected 4 patients, found {len(report)}"

    def test_all_patients_present(self):
        report = load_report()
        for pid in EXPECTED:
            assert pid in report, f"Patient {pid} missing from report"


# -------------------------------------------------------------------
# Tests: Patient 001 — Maria Chen
# -------------------------------------------------------------------

class TestPatient001MariaChen:
    """72F, Scr 2.1 mg/dL (must pick most recent), eGFR ~24.6, CKD G4, CRITICAL."""

    def test_egfr(self):
        report = load_report()
        p = report["pat-001"]
        expected = EXPECTED["pat-001"]["egfr"]
        actual = p["egfr"]
        assert abs(actual - expected) <= 2.0, (
            f"pat-001 eGFR: expected ~{expected:.1f}, got {actual}. "
            "Must use most recent creatinine (2.1, not 1.2)."
        )

    def test_creatinine_selection(self):
        """Agent must have used the most recent creatinine (2.1), not older (1.2)."""
        report = load_report()
        p = report["pat-001"]
        scr = p.get("serum_creatinine_mg_dl", p.get("serum_creatinine", 0))
        assert abs(scr - 2.1) < 0.1, (
            f"pat-001: expected Scr=2.1 mg/dL (most recent), got {scr}. "
            "Must select most recent creatinine observation by effectiveDateTime."
        )

    def test_ckd_stage(self):
        report = load_report()
        assert report["pat-001"]["ckd_stage"] == "G4"

    def test_alert_level(self):
        report = load_report()
        assert report["pat-001"]["alert_level"] == "CRITICAL"

    def test_metformin_stop(self):
        report = load_report()
        med = _find_med(report["pat-001"]["medications"], "metformin")
        assert med is not None, "metformin not found in pat-001 medications"
        assert med["action"] == "STOP", (
            f"metformin should be STOP at eGFR<30, got {med['action']}"
        )

    def test_digoxin_reduce(self):
        report = load_report()
        med = _find_med(report["pat-001"]["medications"], "digoxin")
        assert med is not None, "digoxin not found in pat-001 medications"
        assert med["action"] == "REDUCE", (
            f"digoxin should be REDUCE at eGFR<30, got {med['action']}"
        )

    def test_apixaban_reduce(self):
        """apixaban may appear as 'apixaban' or 'eliquis' — must resolve from RxNorm."""
        report = load_report()
        med = _find_med(report["pat-001"]["medications"], "apixaban")
        if med is None:
            med = _find_med(report["pat-001"]["medications"], "eliquis")
        assert med is not None, (
            "apixaban/eliquis not found in pat-001 medications. "
            "Must resolve generic name from RxNorm coding."
        )
        assert med["action"] == "REDUCE", (
            f"apixaban should be REDUCE at eGFR 15-29, got {med['action']}"
        )

    def test_lisinopril_no_change(self):
        report = load_report()
        med = _find_med(report["pat-001"]["medications"], "lisinopril")
        assert med is not None, "lisinopril not found in pat-001 medications"
        assert med["action"] == "NO_CHANGE", (
            f"lisinopril not in dosing table, should be NO_CHANGE, got {med['action']}"
        )


# -------------------------------------------------------------------
# Tests: Patient 002 — James Walker
# -------------------------------------------------------------------

class TestPatient002JamesWalker:
    """58M, Scr 0.9 mg/dL, eGFR ~99.0, CKD G1, OK."""

    def test_egfr(self):
        report = load_report()
        p = report["pat-002"]
        expected = EXPECTED["pat-002"]["egfr"]
        actual = p["egfr"]
        assert abs(actual - expected) <= 2.0, (
            f"pat-002 eGFR: expected ~{expected:.1f}, got {actual}"
        )

    def test_ckd_stage(self):
        report = load_report()
        assert report["pat-002"]["ckd_stage"] == "G1"

    def test_alert_level(self):
        report = load_report()
        assert report["pat-002"]["alert_level"] == "OK"

    def test_all_meds_no_change(self):
        report = load_report()
        for med in report["pat-002"]["medications"]:
            assert med["action"] == "NO_CHANGE", (
                f"pat-002 all meds should be NO_CHANGE at eGFR>60, "
                f"but {med['drug_name']} has action {med['action']}"
            )


# -------------------------------------------------------------------
# Tests: Patient 003 — Robert Davis
# -------------------------------------------------------------------

class TestPatient003RobertDavis:
    """80M, Scr 309.4 umol/L = 3.5 mg/dL, eGFR ~16.9, CKD G4, CRITICAL."""

    def test_unit_conversion(self):
        """Creatinine is in umol/L in FHIR data; must convert to mg/dL."""
        report = load_report()
        p = report["pat-003"]
        scr = p.get("serum_creatinine_mg_dl", p.get("serum_creatinine", 0))
        assert abs(scr - 3.5) < 0.15, (
            f"pat-003: expected Scr~3.5 mg/dL (309.4 umol/L converted), got {scr}. "
            "Must convert from umol/L to mg/dL."
        )

    def test_egfr(self):
        report = load_report()
        p = report["pat-003"]
        expected = EXPECTED["pat-003"]["egfr"]
        actual = p["egfr"]
        assert abs(actual - expected) <= 2.0, (
            f"pat-003 eGFR: expected ~{expected:.1f}, got {actual}. "
            "Creatinine must be converted from umol/L to mg/dL first."
        )

    def test_ckd_stage(self):
        report = load_report()
        assert report["pat-003"]["ckd_stage"] == "G4"

    def test_alert_level(self):
        report = load_report()
        assert report["pat-003"]["alert_level"] == "CRITICAL"

    def test_gabapentin_reduce(self):
        report = load_report()
        med = _find_med(report["pat-003"]["medications"], "gabapentin")
        assert med is not None, "gabapentin not found in pat-003 medications"
        assert med["action"] == "REDUCE"

    def test_allopurinol_reduce(self):
        report = load_report()
        med = _find_med(report["pat-003"]["medications"], "allopurinol")
        assert med is not None, "allopurinol not found in pat-003 medications"
        assert med["action"] == "REDUCE"

    def test_dabigatran_reduce(self):
        """dabigatran may appear as 'dabigatran' or 'pradaxa'."""
        report = load_report()
        med = _find_med(report["pat-003"]["medications"], "dabigatran")
        if med is None:
            med = _find_med(report["pat-003"]["medications"], "pradaxa")
        assert med is not None, "dabigatran/pradaxa not found in pat-003 medications"
        assert med["action"] == "REDUCE"

    def test_metformin_stop(self):
        report = load_report()
        med = _find_med(report["pat-003"]["medications"], "metformin")
        assert med is not None, "metformin not found in pat-003 medications"
        assert med["action"] == "STOP"


# -------------------------------------------------------------------
# Tests: Patient 004 — Sarah Johnson
# -------------------------------------------------------------------

class TestPatient004SarahJohnson:
    """65F, Scr 1.4 mg/dL, eGFR ~41.8, CKD G3b, ADJUST."""

    def test_egfr(self):
        report = load_report()
        p = report["pat-004"]
        expected = EXPECTED["pat-004"]["egfr"]
        actual = p["egfr"]
        assert abs(actual - expected) <= 2.0, (
            f"pat-004 eGFR: expected ~{expected:.1f}, got {actual}"
        )

    def test_ckd_stage(self):
        report = load_report()
        assert report["pat-004"]["ckd_stage"] == "G3b"

    def test_alert_level(self):
        report = load_report()
        assert report["pat-004"]["alert_level"] == "ADJUST"

    def test_rivaroxaban_reduce(self):
        """rivaroxaban may appear as 'rivaroxaban' or 'xarelto'."""
        report = load_report()
        med = _find_med(report["pat-004"]["medications"], "rivaroxaban")
        if med is None:
            med = _find_med(report["pat-004"]["medications"], "xarelto")
        assert med is not None, (
            "rivaroxaban/xarelto not found in pat-004 medications. "
            "Must resolve generic name from RxNorm coding."
        )
        assert med["action"] == "REDUCE"

    def test_amlodipine_no_change(self):
        report = load_report()
        med = _find_med(report["pat-004"]["medications"], "amlodipine")
        assert med is not None, "amlodipine not found in pat-004 medications"
        assert med["action"] == "NO_CHANGE"

    def test_metformin_reduce(self):
        report = load_report()
        med = _find_med(report["pat-004"]["medications"], "metformin")
        assert med is not None, "metformin not found in pat-004 medications"
        assert med["action"] == "REDUCE", (
            f"metformin should be REDUCE at eGFR 30-59, got {med['action']}"
        )


# -------------------------------------------------------------------
# Tests: Cross-patient consistency
# -------------------------------------------------------------------

class TestCrossPatientConsistency:
    def test_critical_patients_have_stops(self):
        """CRITICAL alert should correspond to at least one STOP."""
        report = load_report()
        for pid in ["pat-001", "pat-003"]:
            p = report[pid]
            if p["alert_level"] == "CRITICAL":
                actions = [m["action"] for m in p["medications"]]
                assert "STOP" in actions, (
                    f"{pid} is CRITICAL but has no STOP actions: {actions}"
                )

    def test_ok_patient_has_no_adjustments(self):
        report = load_report()
        p = report["pat-002"]
        assert p["alert_level"] == "OK"
        for med in p["medications"]:
            assert med["action"] == "NO_CHANGE", (
                f"pat-002 is OK but {med['drug_name']} has action {med['action']}"
            )

    def test_medication_counts(self):
        """Each patient should have the correct number of medications."""
        report = load_report()
        expected_counts = {"pat-001": 4, "pat-002": 3, "pat-003": 4, "pat-004": 3}
        for pid, expected_count in expected_counts.items():
            actual_count = len(report[pid]["medications"])
            assert actual_count == expected_count, (
                f"{pid}: expected {expected_count} medications, got {actual_count}"
            )


# -------------------------------------------------------------------
# Tests: Drug-drug interactions
# -------------------------------------------------------------------

class TestDrugInteractions:
    def test_pat001_digoxin_apixaban(self):
        """pat-001 takes digoxin + apixaban — MODERATE interaction expected."""
        report = load_report()
        interactions = report["pat-001"].get("drug_interactions", [])
        pairs = _get_interaction_pairs(interactions)
        assert ("digoxin", "apixaban") in pairs, (
            "pat-001 missing digoxin-apixaban interaction (MODERATE severity)"
        )

    def test_pat001_metformin_lisinopril(self):
        """pat-001 takes metformin + lisinopril — LOW interaction expected."""
        report = load_report()
        interactions = report["pat-001"].get("drug_interactions", [])
        pairs = _get_interaction_pairs(interactions)
        assert ("metformin", "lisinopril") in pairs, (
            "pat-001 missing metformin-lisinopril interaction"
        )

    def test_pat001_interaction_count(self):
        report = load_report()
        interactions = report["pat-001"].get("drug_interactions", [])
        assert len(interactions) == 2, (
            f"pat-001 should have exactly 2 drug interactions, found {len(interactions)}"
        )

    def test_pat002_metformin_lisinopril(self):
        """pat-002 takes metformin + lisinopril — LOW interaction expected."""
        report = load_report()
        interactions = report["pat-002"].get("drug_interactions", [])
        pairs = _get_interaction_pairs(interactions)
        assert ("metformin", "lisinopril") in pairs, (
            "pat-002 missing metformin-lisinopril interaction"
        )

    def test_pat002_interaction_count(self):
        report = load_report()
        interactions = report["pat-002"].get("drug_interactions", [])
        assert len(interactions) == 1, (
            f"pat-002 should have exactly 1 drug interaction, found {len(interactions)}"
        )

    def test_pat003_dabigatran_allopurinol(self):
        """pat-003 takes dabigatran + allopurinol — MODERATE interaction expected."""
        report = load_report()
        interactions = report["pat-003"].get("drug_interactions", [])
        pairs = _get_interaction_pairs(interactions)
        assert ("dabigatran", "allopurinol") in pairs, (
            "pat-003 missing dabigatran-allopurinol interaction (MODERATE severity)"
        )

    def test_pat003_gabapentin_dabigatran(self):
        """pat-003 takes gabapentin + dabigatran — LOW interaction expected."""
        report = load_report()
        interactions = report["pat-003"].get("drug_interactions", [])
        pairs = _get_interaction_pairs(interactions)
        assert ("gabapentin", "dabigatran") in pairs, (
            "pat-003 missing gabapentin-dabigatran interaction"
        )

    def test_pat003_interaction_count(self):
        report = load_report()
        interactions = report["pat-003"].get("drug_interactions", [])
        assert len(interactions) == 2, (
            f"pat-003 should have exactly 2 drug interactions, found {len(interactions)}"
        )

    def test_pat004_rivaroxaban_amlodipine(self):
        """pat-004 takes rivaroxaban + amlodipine — LOW interaction expected."""
        report = load_report()
        interactions = report["pat-004"].get("drug_interactions", [])
        pairs = _get_interaction_pairs(interactions)
        assert ("rivaroxaban", "amlodipine") in pairs, (
            "pat-004 missing rivaroxaban-amlodipine interaction"
        )

    def test_pat004_interaction_count(self):
        report = load_report()
        interactions = report["pat-004"].get("drug_interactions", [])
        assert len(interactions) == 1, (
            f"pat-004 should have exactly 1 drug interaction, found {len(interactions)}"
        )

    def test_all_interactions_have_required_fields(self):
        """Every interaction entry must have drug_a, drug_b, severity, clinical_effect."""
        report = load_report()
        for pid in ["pat-001", "pat-002", "pat-003", "pat-004"]:
            for ix in report[pid].get("drug_interactions", []):
                assert "drug_a" in ix, f"{pid}: interaction missing 'drug_a'"
                assert "drug_b" in ix, f"{pid}: interaction missing 'drug_b'"
                assert "severity" in ix, f"{pid}: interaction missing 'severity'"
                assert "clinical_effect" in ix, f"{pid}: interaction missing 'clinical_effect'"
                assert ix["severity"] in ("HIGH", "MODERATE", "LOW"), (
                    f"{pid}: invalid severity '{ix['severity']}'"
                )

    def test_moderate_interactions_flagged(self):
        """All MODERATE-severity interactions must be detected."""
        report = load_report()
        # pat-001: digoxin-apixaban is MODERATE
        ix_001 = report["pat-001"].get("drug_interactions", [])
        moderate_001 = [i for i in ix_001 if i.get("severity") == "MODERATE"]
        assert len(moderate_001) >= 1, "pat-001 should have at least 1 MODERATE interaction"

        # pat-003: dabigatran-allopurinol is MODERATE
        ix_003 = report["pat-003"].get("drug_interactions", [])
        moderate_003 = [i for i in ix_003 if i.get("severity") == "MODERATE"]
        assert len(moderate_003) >= 1, "pat-003 should have at least 1 MODERATE interaction"
