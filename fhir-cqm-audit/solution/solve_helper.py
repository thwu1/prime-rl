"""

Solution helper: performs the CQM audit by querying the FHIR server,
evaluating 5 clinical quality measures, and placing corrective orders.
"""

import json
import re
import sys
import requests
from datetime import datetime

FHIR_BASE = "http://localhost:8080/fhir"


def fhir_get(resource_type, params=None):
    resp = requests.get(f"{FHIR_BASE}/{resource_type}", params=params or {}, timeout=10)
    resp.raise_for_status()
    bundle = resp.json()
    return [e["resource"] for e in bundle.get("entry", [])]


def fhir_post(resource_type, resource):
    resp = requests.post(
        f"{FHIR_BASE}/{resource_type}",
        json=resource,
        headers={"Content-Type": "application/fhir+json"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fhir_put(resource_type, resource_id, resource):
    resp = requests.put(
        f"{FHIR_BASE}/{resource_type}/{resource_id}",
        json=resource,
        headers={"Content-Type": "application/fhir+json"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_condition_codes(patient_id):
    conditions = fhir_get("Condition", {"patient": patient_id})
    codes = set()
    for c in conditions:
        for coding in c.get("code", {}).get("coding", []):
            codes.add(coding.get("code", ""))
    return codes


def get_observation_value(patient_id, loinc_code):
    obs = fhir_get("Observation", {"patient": patient_id, "code": loinc_code})
    if obs:
        return obs[0].get("valueQuantity", {}).get("value")
    return None


def get_medications(patient_id):
    return fhir_get("MedicationRequest", {"patient": patient_id})


def has_medication_matching(meds, patterns):
    for med in meds:
        med_text = json.dumps(med.get("medicationCodeableConcept", {})).lower()
        for p in patterns:
            if re.search(p, med_text):
                if med.get("status") == "active":
                    return True
    return False


def get_patient_info(patient_id):
    patients = fhir_get("Patient", {"_id": patient_id})
    if not patients:
        patients = fhir_get(f"Patient/{patient_id}")
        if isinstance(patients, dict):
            patients = [patients]
    if not patients:
        resp = requests.get(f"{FHIR_BASE}/Patient/{patient_id}", timeout=10)
        if resp.status_code == 200:
            patients = [resp.json()]
    return patients[0] if patients else None


def calculate_age(birth_date_str):
    birth = datetime.strptime(birth_date_str, "%Y-%m-%d")
    ref = datetime(2025, 1, 15)
    age = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        age -= 1
    return age


def calculate_cha2ds2vasc(patient, condition_codes):
    score = 0
    chf_codes = {"I50.9", "I50.0", "I50.1", "I50.2", "I50.20", "I50.21", "I50.22",
                 "I50.23", "I50.30", "I50.31", "I50.32", "I50.33", "I50.40", "I50.41",
                 "I50.42", "I50.43", "I50.810", "I50.811", "I50.812", "I50.813",
                 "I50.814", "I50.82", "I50.83", "I50.84", "I50.89", "I50"}
    htn_codes = {"I10", "I11", "I12", "I13", "I15", "I16"}
    dm_codes = set()
    for code in condition_codes:
        if code.startswith("E10") or code.startswith("E11"):
            dm_codes.add(code)
    stroke_codes = {"I63", "G45", "I74"}

    if condition_codes & chf_codes:
        score += 1
    if condition_codes & htn_codes:
        score += 1

    age = calculate_age(patient.get("birthDate", "1960-01-01"))
    if age >= 75:
        score += 2
    elif age >= 65:
        score += 1

    if dm_codes:
        score += 1

    if condition_codes & stroke_codes:
        score += 2

    if patient.get("gender") == "female":
        score += 1

    return score


def create_service_request(patient_id, specialty, description):
    sr = {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "386053000",
                    "display": f"{specialty} referral",
                }
            ],
            "text": f"{specialty} referral",
        },
        "note": [{"text": description}],
        "authoredOn": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return fhir_post("ServiceRequest", sr)


def create_medication_request(patient_id, med_name, med_code, dose_text):
    mr = {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{patient_id}"},
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": med_code,
                    "display": med_name,
                }
            ],
            "text": med_name,
        },
        "dosageInstruction": [{"text": dose_text}],
        "authoredOn": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return fhir_post("MedicationRequest", mr)


def stop_metformin(patient_id):
    meds = get_medications(patient_id)
    for med in meds:
        med_text = json.dumps(med.get("medicationCodeableConcept", {})).lower()
        if re.search(r"metformin", med_text) and med.get("status") == "active":
            med["status"] = "stopped"
            result = fhir_put("MedicationRequest", med["id"], med)
            return result
    sr = {
        "resourceType": "MedicationRequest",
        "status": "stopped",
        "intent": "order",
        "subject": {"reference": f"Patient/{patient_id}"},
        "medicationCodeableConcept": {
            "text": "Metformin - DISCONTINUED due to eGFR < 30",
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "861007",
                    "display": "Metformin hydrochloride 500 MG Oral Tablet",
                }
            ],
        },
        "note": [{"text": "Discontinued: contraindicated with eGFR < 30 mL/min"}],
    }
    return fhir_post("MedicationRequest", sr)


def main():
    patients = fhir_get("Patient")
    report = {"patients": [], "summary": {"total_patients": 0, "patients_with_gaps": 0, "total_gaps": 0}}

    anticoagulant_patterns = [r"warfarin", r"apixaban", r"rivaroxaban", r"dabigatran", r"edoxaban", r"eliquis", r"xarelto", r"pradaxa"]
    statin_patterns = [r"atorvastatin", r"rosuvastatin", r"simvastatin", r"pravastatin", r"lovastatin", r"fluvastatin", r"pitavastatin"]

    for patient in patients:
        pid = patient["id"]
        name_parts = patient.get("name", [{}])[0]
        pname = "{}, {}".format(
            name_parts.get("family", ""),
            " ".join(name_parts.get("given", [])),
        )

        print(f"\n--- Evaluating patient {pid}: {pname} ---")

        conditions = get_condition_codes(pid)
        meds = get_medications(pid)
        hba1c = get_observation_value(pid, "4548-4")
        egfr = get_observation_value(pid, "33914-3")
        ldl = get_observation_value(pid, "2089-1")

        print(f"  Conditions: {conditions}")
        print(f"  HbA1c: {hba1c}, eGFR: {egfr}, LDL: {ldl}")
        print(f"  Active meds: {len(meds)}")

        gaps = []

        # CQM-1: Uncontrolled Diabetes
        has_diabetes = any(c.startswith("E10") or c.startswith("E11") for c in conditions)
        if has_diabetes and hba1c is not None and hba1c >= 9.0:
            print(f"  CQM-1 GAP: HbA1c {hba1c}% >= 9.0%, ordering endocrinology referral")
            result = create_service_request(
                pid, "Endocrinology",
                f"Referral for uncontrolled diabetes. HbA1c: {hba1c}%"
            )
            gaps.append({
                "cqm_id": "CQM-1",
                "description": f"Uncontrolled diabetes with HbA1c {hba1c}%",
                "action": "Endocrinology referral ordered",
                "fhir_resource_id": result.get("id", "unknown"),
            })

        # CQM-2: CKD Medication Safety
        if egfr is not None and egfr < 30 and has_medication_matching(meds, [r"metformin"]):
            print(f"  CQM-2 GAP: eGFR {egfr} < 30 with active metformin, discontinuing")
            result = stop_metformin(pid)
            gaps.append({
                "cqm_id": "CQM-2",
                "description": f"Metformin contraindicated with eGFR {egfr} mL/min",
                "action": "Metformin discontinued",
                "fhir_resource_id": result.get("id", "unknown"),
            })

        # CQM-3: Atrial Fibrillation Anticoagulation
        has_afib = any(c.startswith("I48") for c in conditions)
        if has_afib:
            score = calculate_cha2ds2vasc(patient, conditions)
            print(f"  Afib detected. CHA2DS2-VASc score: {score}")
            if score >= 2:
                on_anticoag = has_medication_matching(meds, anticoagulant_patterns)
                if not on_anticoag:
                    print(f"  CQM-3 GAP: CHA2DS2-VASc {score} >= 2, no anticoagulant")
                    result = create_medication_request(
                        pid,
                        "Apixaban 5 MG Oral Tablet",
                        "1364430",
                        "Take 1 tablet by mouth twice daily",
                    )
                    gaps.append({
                        "cqm_id": "CQM-3",
                        "description": f"Atrial fibrillation with CHA2DS2-VASc score {score}, no anticoagulant",
                        "action": "Apixaban 5mg BID ordered",
                        "fhir_resource_id": result.get("id", "unknown"),
                    })
                else:
                    print(f"  CQM-3 OK: Already on anticoagulant")

        # CQM-4: Statin Therapy
        if ldl is not None and ldl > 190:
            on_statin = has_medication_matching(meds, statin_patterns)
            if not on_statin:
                print(f"  CQM-4 GAP: LDL {ldl} > 190, no statin")
                result = create_medication_request(
                    pid,
                    "Atorvastatin 40 MG Oral Tablet",
                    "259255",
                    "Take 1 tablet by mouth once daily at bedtime",
                )
                gaps.append({
                    "cqm_id": "CQM-4",
                    "description": f"LDL {ldl} mg/dL > 190 without statin therapy",
                    "action": "Atorvastatin 40mg daily ordered",
                    "fhir_resource_id": result.get("id", "unknown"),
                })

        # CQM-5: Nephrology Referral
        if egfr is not None and egfr < 30:
            existing_srs = fhir_get("ServiceRequest", {"patient": pid})
            has_nephro = any(
                re.search(r"nephrolog|renal|kidney", json.dumps(sr).lower())
                for sr in existing_srs
            )
            if not has_nephro:
                print(f"  CQM-5 GAP: eGFR {egfr} < 30, no nephrology referral")
                result = create_service_request(
                    pid, "Nephrology",
                    f"Referral for advanced CKD management. eGFR: {egfr} mL/min"
                )
                gaps.append({
                    "cqm_id": "CQM-5",
                    "description": f"eGFR {egfr} mL/min < 30 without nephrology referral",
                    "action": "Nephrology referral ordered",
                    "fhir_resource_id": result.get("id", "unknown"),
                })

        patient_entry = {
            "patient_id": pid,
            "patient_name": pname,
            "gaps_identified": gaps,
        }
        report["patients"].append(patient_entry)
        report["summary"]["total_patients"] += 1
        if gaps:
            report["summary"]["patients_with_gaps"] += 1
            report["summary"]["total_gaps"] += len(gaps)

    import os
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/cqm_audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n=== AUDIT COMPLETE ===")
    print(f"Total patients: {report['summary']['total_patients']}")
    print(f"Patients with gaps: {report['summary']['patients_with_gaps']}")
    print(f"Total gaps: {report['summary']['total_gaps']}")
    print(f"Report written to /app/output/cqm_audit_report.json")


if __name__ == "__main__":
    main()
