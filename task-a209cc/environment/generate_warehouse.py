#!/usr/bin/env python3
"""Generate a deliberately buggy SQLite warehouse from FHIR NDJSON source data.

Simulates a faulty ETL pipeline with multiple categories of data quality issues.
This script is run during Docker build and then deleted.
"""
import json
import os
import sqlite3

FHIR_DIR = "/app/fhir_data"
DB_PATH = "/app/warehouse.db"


def load_ndjson(filename):
    resources = []
    path = os.path.join(FHIR_DIR, filename)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                resources.append(json.loads(line))
    return resources


def ref_id(ref_str):
    return ref_str.split("/")[-1] if "/" in ref_str else ref_str


# Pre-load medication names for denormalized storage
medications = {}
for m in load_ndjson("Medication.ndjson"):
    coding = m.get("code", {}).get("coding", [])
    medications[m["id"]] = coding[0].get("display", "") if coding else ""


conn = sqlite3.connect(DB_PATH)

conn.executescript("""
CREATE TABLE patients (
    id TEXT PRIMARY KEY,
    given_name TEXT,
    family_name TEXT,
    gender TEXT,
    birth_date TEXT
);

CREATE TABLE encounters (
    id TEXT PRIMARY KEY,
    patient_id TEXT REFERENCES patients(id),
    location_id TEXT,
    class_code TEXT,
    period_start TEXT,
    period_end TEXT
);

CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    patient_id TEXT REFERENCES patients(id),
    encounter_id TEXT REFERENCES encounters(id),
    loinc_code TEXT,
    display TEXT,
    value REAL,
    unit TEXT,
    effective_dt TEXT
);

CREATE TABLE medication_requests (
    id TEXT PRIMARY KEY,
    patient_id TEXT REFERENCES patients(id),
    encounter_id TEXT REFERENCES encounters(id),
    medication_id TEXT,
    medication_name TEXT,
    authored_on TEXT
);

CREATE TABLE conditions (
    id TEXT PRIMARY KEY,
    patient_id TEXT REFERENCES patients(id),
    encounter_id TEXT REFERENCES encounters(id),
    icd_code TEXT,
    display TEXT
);

CREATE TABLE procedures (
    id TEXT PRIMARY KEY,
    patient_id TEXT REFERENCES patients(id),
    encounter_id TEXT REFERENCES encounters(id),
    proc_code TEXT,
    display TEXT,
    performed_dt TEXT
);

CREATE INDEX idx_obs_patient ON observations(patient_id);
CREATE INDEX idx_obs_loinc ON observations(loinc_code);
CREATE INDEX idx_enc_patient ON encounters(patient_id);
CREATE INDEX idx_mr_patient ON medication_requests(patient_id);
""")

# --- Load patients ---
# BUG: patient-003 has given/family names swapped
for p in load_ndjson("Patient.ndjson"):
    names = p.get("name", [{}])
    given = " ".join(names[0].get("given", []))
    family = names[0].get("family", "")
    if p["id"] == "patient-003":
        given, family = family, given
    conn.execute("INSERT INTO patients VALUES (?,?,?,?,?)",
                 (p["id"], given, family, p.get("gender", ""),
                  p.get("birthDate", "")))

# --- Load encounters ---
# BUG: period dates truncated to YYYY-MM-DD (losing time information)
for e in load_ndjson("Encounter.ndjson"):
    period = e.get("period", {})
    start = period.get("start", "")[:10]
    end = period.get("end", "")[:10]
    locs = e.get("location", [])
    loc_id = ref_id(locs[0]["location"]["reference"]) if locs else ""
    cls = e.get("class", {}).get("code", "")
    pid = ref_id(e.get("subject", {}).get("reference", ""))
    conn.execute("INSERT INTO encounters VALUES (?,?,?,?,?,?)",
                 (e["id"], pid, loc_id, cls, start, end))

# --- Load observations ---
# BUG 1: obs-024 silently dropped
# BUG 2: component observations (BP) flattened to systolic only
# BUG 3: phantom observation inserted
for obs in load_ndjson("Observation.ndjson"):
    if obs["id"] == "obs-024":
        continue  # BUG: dropped record

    cc = obs.get("code", {}).get("coding", [{}])[0]
    loinc = cc.get("code", "")
    display = cc.get("display", "")

    value = None
    unit = ""
    if "valueQuantity" in obs:
        value = obs["valueQuantity"].get("value")
        unit = obs["valueQuantity"].get("unit", "")
    elif "component" in obs:
        # BUG: only first component (systolic) stored, diastolic lost
        comp = obs["component"][0]
        vq = comp.get("valueQuantity", {})
        value = vq.get("value")
        unit = vq.get("unit", "")

    pid = ref_id(obs.get("subject", {}).get("reference", ""))
    enc_id = ref_id(obs.get("encounter", {}).get("reference", ""))
    conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
                 (obs["id"], pid, enc_id, loinc, display, value, unit,
                  obs.get("effectiveDateTime", "")))

# BUG: phantom observation that has no FHIR source
conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
             ("obs-phantom", "patient-002", "enc-003", "8867-4",
              "Heart rate", 78, "/min", "2023-03-10T17:00:00Z"))

# --- Load medication requests ---
# BUG 1: medreq-004 linked to wrong patient
# BUG 2: medreq-008 has NULL medication_name despite resolvable reference
for mr in load_ndjson("MedicationRequest.ndjson"):
    pid = ref_id(mr.get("subject", {}).get("reference", ""))
    if mr["id"] == "medreq-004":
        pid = "patient-003"  # BUG: should be patient-002

    enc_id = ref_id(mr.get("encounter", {}).get("reference", ""))
    med_ref = mr.get("medicationReference", {}).get("reference", "")
    med_id = ref_id(med_ref)

    if mr["id"] == "medreq-008":
        mname = None  # BUG: failed to resolve medication
    else:
        mname = medications.get(med_id)

    conn.execute("INSERT INTO medication_requests VALUES (?,?,?,?,?,?)",
                 (mr["id"], pid, enc_id, med_id, mname,
                  mr.get("authoredOn", "")))

# --- Load conditions ---
# BUG: ICD codes have dots stripped for cond-003 and cond-007
for c in load_ndjson("Condition.ndjson"):
    cc = c.get("code", {}).get("coding", [{}])[0]
    icd = cc.get("code", "")
    display = cc.get("display", "")
    if c["id"] in ("cond-003", "cond-007"):
        icd = icd.replace(".", "")  # BUG: format corruption
    pid = ref_id(c.get("subject", {}).get("reference", ""))
    enc_id = ref_id(c.get("encounter", {}).get("reference", ""))
    conn.execute("INSERT INTO conditions VALUES (?,?,?,?,?)",
                 (c["id"], pid, enc_id, icd, display))

# --- Load procedures (clean — no bugs) ---
for p in load_ndjson("Procedure.ndjson"):
    cc = p.get("code", {}).get("coding", [{}])[0]
    proc_code = cc.get("code", "")
    display = cc.get("display", "")
    pid = ref_id(p.get("subject", {}).get("reference", ""))
    enc_id = ref_id(p.get("encounter", {}).get("reference", ""))
    conn.execute("INSERT INTO procedures VALUES (?,?,?,?,?,?)",
                 (p["id"], pid, enc_id, proc_code, display,
                  p.get("performedDateTime", "")))

conn.commit()
conn.close()
print(f"Generated warehouse at {DB_PATH}")
