"""

Pytest tests for the FHIR Clinical Quality Measures Audit task.

Verifies that the agent correctly identified care gaps and placed
appropriate FHIR orders (ServiceRequests and MedicationRequests)
for each of the 5 clinical quality measures across 6 patients.
"""

import json
import os
import re
import requests
import pytest

FHIR_BASE = "http://localhost:8080/fhir"

ANTICOAGULANT_PATTERNS = [
    r"warfarin", r"apixaban", r"eliquis", r"rivaroxaban", r"xarelto",
    r"dabigatran", r"pradaxa", r"edoxaban", r"savaysa", r"anticoagul",
]

STATIN_PATTERNS = [
    r"atorvastatin", r"rosuvastatin", r"simvastatin", r"pravastatin",
    r"lovastatin", r"fluvastatin", r"pitavastatin", r"statin", r"lipitor",
    r"crestor", r"zocor",
]

METFORMIN_PATTERNS = [r"metformin", r"glucophage"]

ENDOCRINOLOGY_PATTERNS = [
    r"endocrinolog", r"diabetes.*referral", r"diabetes.*consult",
    r"diabetes.*specialist", r"endocrine",
]

NEPHROLOGY_PATTERNS = [
    r"nephrolog", r"kidney.*referral", r"kidney.*consult",
    r"renal.*referral", r"renal.*consult", r"kidney.*specialist",
    r"renal.*specialist",
]


def get_resources(resource_type, patient_id=None):
    params = {}
    if patient_id:
        params["patient"] = patient_id
    resp = requests.get(f"{FHIR_BASE}/{resource_type}", params=params, timeout=10)
    assert resp.status_code == 200, f"Failed to query {resource_type}: {resp.status_code}"
    bundle = resp.json()
    return [e["resource"] for e in bundle.get("entry", [])]


def get_initial_ids():
    resp = requests.get(f"{FHIR_BASE}/_initial_ids", timeout=10)
    assert resp.status_code == 200, "Failed to get initial IDs"
    return resp.json()


def get_new_resources(resource_type, patient_id=None):
    initial_ids = get_initial_ids()
    known_ids = set(initial_ids.get(resource_type, []))
    all_resources = get_resources(resource_type, patient_id)
    return [r for r in all_resources if r.get("id") not in known_ids]


def resource_matches_patterns(resource, patterns, fields=None):
    if fields is None:
        fields = ["code", "medicationCodeableConcept"]
    text = ""
    for field in fields:
        obj = resource.get(field, {})
        if isinstance(obj, dict):
            text += " " + json.dumps(obj).lower()
    text += " " + resource.get("description", "").lower()
    for note in resource.get("note", []):
        text += " " + note.get("text", "").lower()
    return any(re.search(p, text) for p in patterns)


def medication_status_stopped(resource):
    return resource.get("status") in ("stopped", "cancelled", "entered-in-error")


# ============================================================
# CQM-1: Uncontrolled Diabetes - Endocrinology Referral
# Patient pt-001 (Maria Lopez): HbA1c 10.2%, needs referral
# ============================================================

def test_cqm1_endocrinology_referral_pt001():
    """pt-001 (Maria Lopez) has HbA1c 10.2% with diabetes.
    Must have a ServiceRequest for endocrinology referral."""
    new_srs = get_new_resources("ServiceRequest", "pt-001")
    matching = [
        sr for sr in new_srs
        if resource_matches_patterns(sr, ENDOCRINOLOGY_PATTERNS)
    ]
    assert len(matching) >= 1, (
        f"CQM-1 FAIL: No endocrinology referral ServiceRequest found for pt-001. "
        f"Found {len(new_srs)} new ServiceRequest(s): "
        f"{[json.dumps(sr.get('code', sr.get('description', ''))) for sr in new_srs]}"
    )


# ============================================================
# CQM-2: CKD Medication Safety - Discontinue Metformin
# Patient pt-002 (James Chen): eGFR 22, on metformin
# ============================================================

def test_cqm2_metformin_stopped_pt002():
    """pt-002 (James Chen) has eGFR 22 and is on metformin.
    Metformin must be discontinued (status stopped/cancelled)."""
    all_meds = get_resources("MedicationRequest", "pt-002")
    metformin_meds = [
        m for m in all_meds
        if resource_matches_patterns(m, METFORMIN_PATTERNS)
    ]
    assert len(metformin_meds) > 0, "No metformin MedicationRequest found for pt-002"

    stopped = [m for m in metformin_meds if medication_status_stopped(m)]
    original_updated = any(
        m.get("id") == "med-002-1" and medication_status_stopped(m)
        for m in metformin_meds
    )
    new_stopped = any(
        m.get("id") != "med-002-1" and medication_status_stopped(m)
        for m in metformin_meds
    )

    assert original_updated or new_stopped or len(stopped) > 0, (
        "CQM-2 FAIL: Metformin for pt-002 not discontinued. "
        f"Metformin statuses: {[m.get('status') for m in metformin_meds]}"
    )


# ============================================================
# CQM-3: Atrial Fibrillation Anticoagulation
# Patient pt-003 (Sarah Johnson): Afib, CHA2DS2-VASc=5, no anticoag
# ============================================================

def test_cqm3_anticoagulation_ordered_pt003():
    """pt-003 (Sarah Johnson) has Afib with CHA2DS2-VASc=5
    and no anticoagulant. Must have anticoagulant ordered."""
    new_meds = get_new_resources("MedicationRequest", "pt-003")
    matching = [
        m for m in new_meds
        if resource_matches_patterns(m, ANTICOAGULANT_PATTERNS)
        and m.get("status") in ("active", "draft", None)
    ]
    assert len(matching) >= 1, (
        f"CQM-3 FAIL: No anticoagulant MedicationRequest found for pt-003. "
        f"Found {len(new_meds)} new MedicationRequest(s): "
        f"{[json.dumps(m.get('medicationCodeableConcept', m.get('code', ''))) for m in new_meds]}"
    )


def test_cqm3_no_anticoagulation_pt005():
    """pt-005 (Elena Rodriguez) has Afib but is already on warfarin.
    Should NOT have a new anticoagulant ordered."""
    new_meds = get_new_resources("MedicationRequest", "pt-005")
    matching = [
        m for m in new_meds
        if resource_matches_patterns(m, ANTICOAGULANT_PATTERNS)
        and m.get("status") in ("active", "draft", None)
    ]
    assert len(matching) == 0, (
        f"CQM-3 FALSE POSITIVE: Anticoagulant ordered for pt-005 who is already on warfarin. "
        f"Found: {[json.dumps(m.get('medicationCodeableConcept', '')) for m in matching]}"
    )


# ============================================================
# CQM-4: Statin Therapy for Severe Hyperlipidemia
# Patient pt-004 (Robert Williams): LDL 215, no statin
# ============================================================

def test_cqm4_statin_ordered_pt004():
    """pt-004 (Robert Williams) has LDL 215 mg/dL with no statin.
    Must have a statin MedicationRequest ordered."""
    new_meds = get_new_resources("MedicationRequest", "pt-004")
    matching = [
        m for m in new_meds
        if resource_matches_patterns(m, STATIN_PATTERNS)
    ]
    assert len(matching) >= 1, (
        f"CQM-4 FAIL: No statin MedicationRequest found for pt-004. "
        f"Found {len(new_meds)} new MedicationRequest(s): "
        f"{[json.dumps(m.get('medicationCodeableConcept', m.get('code', ''))) for m in new_meds]}"
    )


# ============================================================
# CQM-5: Nephrology Referral for Advanced CKD
# Patients pt-002 (eGFR 22) and pt-005 (eGFR 12)
# ============================================================

def test_cqm5_nephrology_referral_pt002():
    """pt-002 (James Chen) has eGFR 22. Must have nephrology referral."""
    new_srs = get_new_resources("ServiceRequest", "pt-002")
    matching = [
        sr for sr in new_srs
        if resource_matches_patterns(sr, NEPHROLOGY_PATTERNS)
    ]
    assert len(matching) >= 1, (
        f"CQM-5 FAIL: No nephrology referral ServiceRequest found for pt-002. "
        f"Found {len(new_srs)} new ServiceRequest(s): "
        f"{[json.dumps(sr.get('code', sr.get('description', ''))) for sr in new_srs]}"
    )


def test_cqm5_nephrology_referral_pt005():
    """pt-005 (Elena Rodriguez) has eGFR 12. Must have nephrology referral."""
    new_srs = get_new_resources("ServiceRequest", "pt-005")
    matching = [
        sr for sr in new_srs
        if resource_matches_patterns(sr, NEPHROLOGY_PATTERNS)
    ]
    assert len(matching) >= 1, (
        f"CQM-5 FAIL: No nephrology referral ServiceRequest found for pt-005. "
        f"Found {len(new_srs)} new ServiceRequest(s): "
        f"{[json.dumps(sr.get('code', sr.get('description', ''))) for sr in new_srs]}"
    )


# ============================================================
# No-gap patient: pt-006 (Michael Thompson)
# ============================================================

def test_no_unnecessary_orders_pt006():
    """pt-006 (Michael Thompson) is well-controlled with no gaps.
    Should have zero new ServiceRequests or MedicationRequests."""
    new_srs = get_new_resources("ServiceRequest", "pt-006")
    new_meds = get_new_resources("MedicationRequest", "pt-006")
    total_new = len(new_srs) + len(new_meds)
    assert total_new == 0, (
        f"FALSE POSITIVE: pt-006 should have no care gaps but received "
        f"{len(new_srs)} new ServiceRequest(s) and {len(new_meds)} new MedicationRequest(s)"
    )


# ============================================================
# Audit Report Validation
# ============================================================

def test_audit_report_exists():
    """Audit report JSON must exist at /app/output/cqm_audit_report.json."""
    report_path = "/app/output/cqm_audit_report.json"
    assert os.path.exists(report_path), f"Audit report not found at {report_path}"
    with open(report_path) as f:
        data = json.load(f)
    assert "patients" in data, "Report missing 'patients' key"
    assert isinstance(data["patients"], list), "'patients' must be a list"
    assert len(data["patients"]) >= 5, (
        f"Report should cover at least 5 patients with gaps or clean audits, "
        f"found {len(data['patients'])}"
    )


def test_audit_report_gap_counts():
    """Audit report must identify correct number of patients with gaps."""
    report_path = "/app/output/cqm_audit_report.json"
    if not os.path.exists(report_path):
        pytest.skip("No audit report found")
    with open(report_path) as f:
        data = json.load(f)

    patients_with_gaps = 0
    total_gaps = 0
    for patient in data.get("patients", []):
        gaps = patient.get("gaps_identified", patient.get("gaps", []))
        if len(gaps) > 0:
            patients_with_gaps += 1
            total_gaps += len(gaps)

    assert patients_with_gaps >= 4, (
        f"Expected at least 4 patients with care gaps (pt-001, pt-002, pt-003, pt-004), "
        f"report shows {patients_with_gaps}"
    )
    assert total_gaps >= 6, (
        f"Expected at least 6 total care gaps, report shows {total_gaps}. "
        f"Expected: CQM-1(pt-001), CQM-2(pt-002), CQM-5(pt-002), "
        f"CQM-3(pt-003), CQM-4(pt-004), CQM-5(pt-005)"
    )
