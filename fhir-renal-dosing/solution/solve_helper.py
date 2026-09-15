"""

Solution: Medication Safety Audit
Parses FHIR R4 Bundles, computes eGFR via CKD-EPI 2021, queries SQLite
pharmacology database for renal dosing adjustments and drug interactions.
"""

import json
import os
import sqlite3
from datetime import datetime
from glob import glob


# ── CKD-EPI 2021 race-free equation ──────────────────────────────────────────

def ckd_epi_2021(scr_mg_dl: float, age: int, is_female: bool) -> float:
    kappa = 0.7 if is_female else 0.9
    alpha = -0.241 if is_female else -0.302
    ratio = scr_mg_dl / kappa
    egfr = (
        142.0
        * min(ratio, 1.0) ** alpha
        * max(ratio, 1.0) ** (-1.200)
        * 0.9938 ** age
    )
    if is_female:
        egfr *= 1.012
    return round(egfr, 1)


def ckd_stage(egfr: float) -> str:
    if egfr >= 90:
        return "G1"
    elif egfr >= 60:
        return "G2"
    elif egfr >= 45:
        return "G3a"
    elif egfr >= 30:
        return "G3b"
    elif egfr >= 15:
        return "G4"
    else:
        return "G5"


# ── FHIR parsing helpers ─────────────────────────────────────────────────────

CREATININE_LOINC = "2160-0"

RXNORM_GENERIC_MAP = {
    "metformin": "metformin",
    "digoxin": "digoxin",
    "apixaban": "apixaban",
    "lisinopril": "lisinopril",
    "atorvastatin": "atorvastatin",
    "gabapentin": "gabapentin",
    "allopurinol": "allopurinol",
    "dabigatran": "dabigatran",
    "rivaroxaban": "rivaroxaban",
    "amlodipine": "amlodipine",
}


def resolve_generic_name(med_concept: dict) -> str:
    """Resolve generic drug name from medicationCodeableConcept."""
    for coding in med_concept.get("coding", []):
        display = coding.get("display", "").lower()
        for key, generic in RXNORM_GENERIC_MAP.items():
            if key in display:
                return generic
    text = med_concept.get("text", "").lower()
    for key, generic in RXNORM_GENERIC_MAP.items():
        if key in text:
            return generic
    return med_concept.get("text", "unknown").lower()


def extract_current_dose(med_request: dict) -> str:
    """Extract human-readable current dose from MedicationRequest."""
    dosage_list = med_request.get("dosageInstruction", [])
    if dosage_list:
        return dosage_list[0].get("text", "unknown")
    return "unknown"


def parse_bundle(filepath: str) -> dict:
    """Parse a FHIR Bundle and return structured patient data."""
    with open(filepath) as f:
        bundle = json.load(f)

    patient = None
    creatinine_obs = []
    medications = []

    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rtype = res.get("resourceType")

        if rtype == "Patient":
            patient = res

        elif rtype == "Observation":
            codes = [
                c.get("code", "")
                for c in res.get("code", {}).get("coding", [])
            ]
            if CREATININE_LOINC in codes:
                vq = res.get("valueQuantity")
                if vq:
                    creatinine_obs.append({
                        "value": vq["value"],
                        "unit": vq.get("unit", vq.get("code", "mg/dL")),
                        "date": res.get("effectiveDateTime", ""),
                    })
            # Also check components (panel observations)
            for comp in res.get("component", []):
                comp_codes = [
                    c.get("code", "")
                    for c in comp.get("code", {}).get("coding", [])
                ]
                if CREATININE_LOINC in comp_codes:
                    vq = comp.get("valueQuantity")
                    if vq:
                        creatinine_obs.append({
                            "value": vq["value"],
                            "unit": vq.get("unit", vq.get("code", "mg/dL")),
                            "date": res.get("effectiveDateTime", ""),
                        })

        elif rtype == "MedicationRequest":
            if res.get("status") == "active":
                medications.append(res)

    return {
        "patient": patient,
        "creatinine_obs": creatinine_obs,
        "medications": medications,
    }


def compute_age(birth_date_str: str, ref_date_str: str) -> int:
    """Compute age in years from birth date and reference date."""
    bd = datetime.strptime(birth_date_str, "%Y-%m-%d")
    ref_str = ref_date_str.split("T")[0]
    ref = datetime.strptime(ref_str, "%Y-%m-%d")
    age = ref.year - bd.year
    if (ref.month, ref.day) < (bd.month, bd.day):
        age -= 1
    return age


def convert_creatinine_to_mg_dl(value: float, unit: str) -> float:
    """Convert creatinine to mg/dL if needed."""
    unit_lower = unit.lower().replace(" ", "")
    if "umol" in unit_lower or "\u00b5mol" in unit_lower:
        return value / 88.4
    return value


# ── SQLite pharmacology queries ──────────────────────────────────────────────

def get_dosing_action(drug_name: str, egfr_val: float, db: sqlite3.Connection) -> tuple:
    """Query renal_adjustments table for dosing action at given eGFR."""
    cursor = db.execute(
        "SELECT action, adjusted_dose FROM renal_adjustments "
        "WHERE drug_name = ? AND ? >= egfr_min AND ? < egfr_max",
        (drug_name, egfr_val, egfr_val),
    )
    row = cursor.fetchone()
    if row is None:
        return ("NO_CHANGE", None)
    action, adjusted_dose = row
    if action == "STOP":
        return ("STOP", None)
    elif action == "REDUCE":
        return ("REDUCE", adjusted_dose)
    else:
        return ("NO_CHANGE", None)


def get_drug_interactions(drug_names: list, db: sqlite3.Connection) -> list:
    """Query drug_interactions table for all pairwise interactions."""
    interactions = []
    for i, drug_a in enumerate(drug_names):
        for drug_b in drug_names[i + 1:]:
            cursor = db.execute(
                "SELECT drug_a, drug_b, severity, clinical_effect "
                "FROM drug_interactions "
                "WHERE (drug_a = ? AND drug_b = ?) OR (drug_a = ? AND drug_b = ?)",
                (drug_a, drug_b, drug_b, drug_a),
            )
            row = cursor.fetchone()
            if row:
                interactions.append({
                    "drug_a": row[0],
                    "drug_b": row[1],
                    "severity": row[2],
                    "clinical_effect": row[3],
                })
    return interactions


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main():
    data_dir = "/app/patient_data"
    db = sqlite3.connect("/app/pharmacology.db")
    results = []

    for fpath in sorted(glob(os.path.join(data_dir, "pat-*.json"))):
        parsed = parse_bundle(fpath)
        patient = parsed["patient"]
        pid = patient["id"]
        name_parts = patient["name"][0]
        full_name = (
            " ".join(name_parts.get("given", []))
            + " "
            + name_parts.get("family", "")
        )
        is_female = patient["gender"] == "female"
        sex = "female" if is_female else "male"

        # Select most recent creatinine
        cr_obs = sorted(
            parsed["creatinine_obs"], key=lambda x: x["date"], reverse=True
        )
        assert cr_obs, f"No creatinine observations found for {pid}"
        latest_cr = cr_obs[0]
        scr_mg_dl = convert_creatinine_to_mg_dl(latest_cr["value"], latest_cr["unit"])

        # Compute age relative to creatinine observation date
        age = compute_age(patient["birthDate"], latest_cr["date"])

        # Compute eGFR and CKD stage
        egfr_val = ckd_epi_2021(scr_mg_dl, age, is_female)
        stage = ckd_stage(egfr_val)

        # Process medications
        med_results = []
        has_stop = False
        has_reduce = False
        drug_names = []

        for med_req in parsed["medications"]:
            concept = med_req.get("medicationCodeableConcept", {})
            generic = resolve_generic_name(concept)
            drug_names.append(generic)
            current_dose = extract_current_dose(med_req)
            action, rec_dose = get_dosing_action(generic, egfr_val, db)

            if action == "STOP":
                has_stop = True
            elif action == "REDUCE":
                has_reduce = True

            med_results.append({
                "drug_name": generic,
                "current_dose": current_dose,
                "action": action,
                "recommended_dose": rec_dose,
            })

        # Alert level
        if has_stop:
            alert = "CRITICAL"
        elif has_reduce:
            alert = "ADJUST"
        else:
            alert = "OK"

        # Drug-drug interactions
        interactions = get_drug_interactions(drug_names, db)

        results.append({
            "patient_id": pid,
            "name": full_name.strip(),
            "age": age,
            "sex": sex,
            "serum_creatinine_mg_dl": round(scr_mg_dl, 2),
            "egfr": egfr_val,
            "ckd_stage": stage,
            "alert_level": alert,
            "medications": med_results,
            "drug_interactions": interactions,
        })

    db.close()

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/renal_dosing_report.json", "w") as f:
        json.dump({"patients": results}, f, indent=2)

    print(f"Report written with {len(results)} patients")
    for r in results:
        print(
            f"  {r['patient_id']}: eGFR={r['egfr']}, CKD={r['ckd_stage']}, "
            f"alert={r['alert_level']}, interactions={len(r['drug_interactions'])}"
        )


if __name__ == "__main__":
    main()
