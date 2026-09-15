#!/usr/bin/env python3
"""FHIR R4 Clinical Data Warehouse Reconciliation Tool.

Audits a SQLite warehouse against FHIR R4 NDJSON source files,
discovers all ETL-introduced discrepancies, repairs the warehouse,
and produces a structured audit report.
"""

import json
import os
import sqlite3
from collections import defaultdict

FHIR_DIR = "/app/fhir_data"
DB_PATH = "/app/warehouse.db"
REPORT_PATH = "/app/audit_report.json"


# ── FHIR Data Loading ───────────────────────────────────────────────────

def load_ndjson(filepath):
    resources = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                resources.append(json.loads(line))
    return resources


def load_all_fhir(data_dir):
    all_resources = {}
    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".ndjson"):
            rtype = fname.rsplit(".", 1)[0]
            resources = load_ndjson(os.path.join(data_dir, fname))
            all_resources[rtype] = {r["id"]: r for r in resources}
    return all_resources


# ── Helpers ──────────────────────────────────────────────────────────────

def ref_id(ref_str):
    return ref_str.split("/")[-1] if "/" in ref_str else ref_str


def patient_name(patient):
    names = patient.get("name", [{}])
    given = " ".join(names[0].get("given", []))
    family = names[0].get("family", "")
    return given, family


def medication_display(med_resource):
    if not med_resource:
        return None
    coding = med_resource.get("code", {}).get("coding", [])
    if coding:
        return coding[0].get("display")
    return med_resource.get("code", {}).get("text")


# ── Reconciliation ───────────────────────────────────────────────────────

def reconcile():
    fhir = load_all_fhir(FHIR_DIR)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    discrepancies = []

    def add(resource_id, resource_type, category, **kwargs):
        d = {"resource_id": resource_id, "resource_type": resource_type,
             "category": category}
        d.update(kwargs)
        discrepancies.append(d)

    # ── Patients ─────────────────────────────────────────────────────
    for pid, p in fhir.get("Patient", {}).items():
        given, family = patient_name(p)
        row = conn.execute(
            "SELECT * FROM patients WHERE id=?", (pid,)
        ).fetchone()
        if not row:
            add(pid, "Patient", "missing_from_warehouse")
            conn.execute(
                "INSERT INTO patients VALUES (?,?,?,?,?)",
                (pid, given, family, p.get("gender", ""),
                 p.get("birthDate", ""))
            )
            continue

        if row["given_name"] != given:
            add(pid, "Patient", "field_mismatch",
                field="given_name", expected=given,
                actual=row["given_name"])
        if row["family_name"] != family:
            add(pid, "Patient", "field_mismatch",
                field="family_name", expected=family,
                actual=row["family_name"])

        conn.execute(
            "UPDATE patients SET given_name=?, family_name=? WHERE id=?",
            (given, family, pid)
        )

    # Phantom patients
    wh_pids = {r["id"] for r in conn.execute("SELECT id FROM patients")}
    for phantom in wh_pids - set(fhir.get("Patient", {}).keys()):
        add(phantom, "Patient", "phantom_record")
        conn.execute("DELETE FROM patients WHERE id=?", (phantom,))

    # ── Encounters ───────────────────────────────────────────────────
    for eid, enc in fhir.get("Encounter", {}).items():
        period = enc.get("period", {})
        exp_start = period.get("start", "")
        exp_end = period.get("end", "")
        patient_id = ref_id(enc.get("subject", {}).get("reference", ""))
        locs = enc.get("location", [])
        loc_id = (ref_id(locs[0]["location"]["reference"])
                  if locs else "")
        cls = enc.get("class", {}).get("code", "")

        row = conn.execute(
            "SELECT * FROM encounters WHERE id=?", (eid,)
        ).fetchone()
        if not row:
            add(eid, "Encounter", "missing_from_warehouse")
            conn.execute(
                "INSERT INTO encounters VALUES (?,?,?,?,?,?)",
                (eid, patient_id, loc_id, cls, exp_start, exp_end)
            )
            continue

        if row["period_start"] != exp_start:
            add(eid, "Encounter", "date_truncation",
                field="period_start",
                expected=exp_start, actual=row["period_start"])
        if row["period_end"] != exp_end:
            add(eid, "Encounter", "date_truncation",
                field="period_end",
                expected=exp_end, actual=row["period_end"])

        conn.execute(
            "UPDATE encounters SET period_start=?, period_end=?, "
            "patient_id=?, location_id=?, class_code=? WHERE id=?",
            (exp_start, exp_end, patient_id, loc_id, cls, eid)
        )

    for phantom in ({r["id"] for r in
                     conn.execute("SELECT id FROM encounters")}
                    - set(fhir.get("Encounter", {}).keys())):
        add(phantom, "Encounter", "phantom_record")
        conn.execute("DELETE FROM encounters WHERE id=?", (phantom,))

    # ── Observations ─────────────────────────────────────────────────
    fhir_obs = fhir.get("Observation", {})
    wh_obs = {r["id"] for r in
              conn.execute("SELECT id FROM observations")}

    for oid, obs in fhir_obs.items():
        cc = obs.get("code", {}).get("coding", [{}])[0]
        loinc = cc.get("code", "")
        display = cc.get("display", "")
        patient_id = ref_id(
            obs.get("subject", {}).get("reference", ""))
        enc_id = ref_id(
            obs.get("encounter", {}).get("reference", ""))
        eff = obs.get("effectiveDateTime", "")
        vq = obs.get("valueQuantity")
        val = vq.get("value") if vq else None
        unit = vq.get("unit", "") if vq else ""

        if oid not in wh_obs:
            add(oid, "Observation", "missing_from_warehouse",
                details=f"{display} ({loinc}) for {patient_id}")
            conn.execute(
                "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
                (oid, patient_id, enc_id, loinc, display,
                 val, unit, eff)
            )
        else:
            row = conn.execute(
                "SELECT * FROM observations WHERE id=?", (oid,)
            ).fetchone()

            # Detect component data loss
            if "component" in obs and vq is None:
                comps = []
                for c in obs["component"]:
                    ccc = c.get("code", {}).get("coding", [{}])[0]
                    cvq = c.get("valueQuantity", {})
                    comps.append({
                        "code": ccc.get("code", ""),
                        "display": ccc.get("display", ""),
                        "value": cvq.get("value"),
                        "unit": cvq.get("unit", "")
                    })
                add(oid, "Observation", "component_data_loss",
                    details=("Component observation flattened to "
                             "single value; diastolic data lost"),
                    expected_components=comps,
                    actual_value=row["value"] if row else None)

    # Phantom observations
    for phantom in wh_obs - set(fhir_obs.keys()):
        add(phantom, "Observation", "phantom_record",
            details="Record in warehouse with no FHIR source")
        conn.execute(
            "DELETE FROM observations WHERE id=?", (phantom,))

    # ── MedicationRequests ───────────────────────────────────────────
    meds = fhir.get("Medication", {})
    fhir_mr = fhir.get("MedicationRequest", {})
    wh_mr = {r["id"] for r in
             conn.execute("SELECT id FROM medication_requests")}

    for mrid, mr in fhir_mr.items():
        exp_pid = ref_id(
            mr.get("subject", {}).get("reference", ""))
        enc_id = ref_id(
            mr.get("encounter", {}).get("reference", ""))
        mref = mr.get("medicationReference", {}).get("reference", "")
        mid = ref_id(mref)
        exp_mname = medication_display(meds.get(mid))

        if mrid not in wh_mr:
            add(mrid, "MedicationRequest", "missing_from_warehouse")
            conn.execute(
                "INSERT INTO medication_requests VALUES (?,?,?,?,?,?)",
                (mrid, exp_pid, enc_id, mid, exp_mname,
                 mr.get("authoredOn", ""))
            )
            continue

        row = conn.execute(
            "SELECT * FROM medication_requests WHERE id=?", (mrid,)
        ).fetchone()

        if row["patient_id"] != exp_pid:
            add(mrid, "MedicationRequest", "wrong_foreign_key",
                field="patient_id",
                expected=exp_pid, actual=row["patient_id"])
            conn.execute(
                "UPDATE medication_requests SET patient_id=? WHERE id=?",
                (exp_pid, mrid)
            )

        if exp_mname and row["medication_name"] != exp_mname:
            add(mrid, "MedicationRequest", "unresolved_reference",
                field="medication_name",
                expected=exp_mname, actual=row["medication_name"])
            conn.execute(
                "UPDATE medication_requests "
                "SET medication_name=? WHERE id=?",
                (exp_mname, mrid)
            )

    for phantom in wh_mr - set(fhir_mr.keys()):
        add(phantom, "MedicationRequest", "phantom_record")
        conn.execute(
            "DELETE FROM medication_requests WHERE id=?", (phantom,))

    # ── Conditions ───────────────────────────────────────────────────
    fhir_conds = fhir.get("Condition", {})
    wh_conds = {r["id"] for r in
                conn.execute("SELECT id FROM conditions")}

    for cid, cond in fhir_conds.items():
        cc = cond.get("code", {}).get("coding", [{}])[0]
        exp_icd = cc.get("code", "")
        display = cc.get("display", "")
        pid = ref_id(cond.get("subject", {}).get("reference", ""))
        enc_id = ref_id(
            cond.get("encounter", {}).get("reference", ""))

        if cid not in wh_conds:
            add(cid, "Condition", "missing_from_warehouse")
            conn.execute(
                "INSERT INTO conditions VALUES (?,?,?,?,?)",
                (cid, pid, enc_id, exp_icd, display)
            )
            continue

        row = conn.execute(
            "SELECT * FROM conditions WHERE id=?", (cid,)
        ).fetchone()

        if row["icd_code"] != exp_icd:
            add(cid, "Condition", "format_corruption",
                field="icd_code",
                expected=exp_icd, actual=row["icd_code"])
            conn.execute(
                "UPDATE conditions SET icd_code=? WHERE id=?",
                (exp_icd, cid)
            )

    for phantom in wh_conds - set(fhir_conds.keys()):
        add(phantom, "Condition", "phantom_record")
        conn.execute(
            "DELETE FROM conditions WHERE id=?", (phantom,))

    # ── Procedures ───────────────────────────────────────────────────
    fhir_procs = fhir.get("Procedure", {})
    wh_procs = {r["id"] for r in
                conn.execute("SELECT id FROM procedures")}

    for procid, proc in fhir_procs.items():
        cc = proc.get("code", {}).get("coding", [{}])[0]
        pc = cc.get("code", "")
        display = cc.get("display", "")
        pid = ref_id(proc.get("subject", {}).get("reference", ""))
        enc_id = ref_id(
            proc.get("encounter", {}).get("reference", ""))
        perf = proc.get("performedDateTime", "")

        if procid not in wh_procs:
            add(procid, "Procedure", "missing_from_warehouse")
            conn.execute(
                "INSERT INTO procedures VALUES (?,?,?,?,?,?)",
                (procid, pid, enc_id, pc, display, perf)
            )

    for phantom in wh_procs - set(fhir_procs.keys()):
        add(phantom, "Procedure", "phantom_record")
        conn.execute(
            "DELETE FROM procedures WHERE id=?", (phantom,))

    # ── Finalize ─────────────────────────────────────────────────────
    conn.commit()
    conn.close()

    cats = defaultdict(int)
    for d in discrepancies:
        cats[d["category"]] += 1

    report = {
        "discrepancies": discrepancies,
        "summary": {
            "total_discrepancies": len(discrepancies),
            "by_category": dict(cats)
        }
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Reconciliation complete: {len(discrepancies)} discrepancies "
          f"across {len(cats)} categories")
    print(f"Report: {REPORT_PATH}")
    print(f"Warehouse repaired: {DB_PATH}")


if __name__ == "__main__":
    reconcile()
