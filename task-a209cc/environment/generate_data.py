#!/usr/bin/env python3
"""Generate synthetic FHIR R4 NDJSON data for the task environment.

Creates interlinked clinical resources for 5 patients with deliberate
integrity issues for the agent to detect.
"""
import json
import os

OUTPUT = "/app/fhir_data"
os.makedirs(OUTPUT, exist_ok=True)


def write_ndjson(filename, resources):
    with open(os.path.join(OUTPUT, filename), "w") as f:
        for r in resources:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def make_obs(oid, code, display, value, unit, patient, encounter, dt):
    return {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "code": {
            "coding": [
                {"system": "http://loinc.org", "code": code, "display": display}
            ],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient}"},
        "encounter": {"reference": f"Encounter/{encounter}"},
        "effectiveDateTime": dt,
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
        },
    }


def make_bp(oid, systolic, diastolic, patient, encounter, dt):
    return {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood pressure panel",
                }
            ],
            "text": "Blood pressure panel",
        },
        "subject": {"reference": f"Patient/{patient}"},
        "encounter": {"reference": f"Encounter/{encounter}"},
        "effectiveDateTime": dt,
        "component": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8480-6",
                            "display": "Systolic blood pressure",
                        }
                    ]
                },
                "valueQuantity": {
                    "value": systolic,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                },
            },
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8462-4",
                            "display": "Diastolic blood pressure",
                        }
                    ]
                },
                "valueQuantity": {
                    "value": diastolic,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                },
            },
        ],
    }


def make_enc(eid, patient, loc, start, end, cls_code="IMP", cls_disp="inpatient encounter"):
    return {
        "resourceType": "Encounter",
        "id": eid,
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": cls_code,
            "display": cls_disp,
        },
        "subject": {"reference": f"Patient/{patient}"},
        "period": {"start": start, "end": end},
        "location": [{"location": {"reference": f"Location/{loc}"}}],
    }


def make_medreq(mrid, patient, encounter, med_id, authored):
    return {
        "resourceType": "MedicationRequest",
        "id": mrid,
        "status": "completed",
        "intent": "order",
        "medicationReference": {"reference": f"Medication/{med_id}"},
        "subject": {"reference": f"Patient/{patient}"},
        "encounter": {"reference": f"Encounter/{encounter}"},
        "authoredOn": authored,
    }


def make_cond(cid, icd, display, patient, encounter):
    return {
        "resourceType": "Condition",
        "id": cid,
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": icd,
                    "display": display,
                }
            ],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient}"},
        "encounter": {"reference": f"Encounter/{encounter}"},
    }


def make_proc(pid, code_val, display, patient, encounter, performed):
    return {
        "resourceType": "Procedure",
        "id": pid,
        "status": "completed",
        "code": {
            "coding": [
                {
                    "system": "http://www.cms.gov/Medicare/Coding/ICD10",
                    "code": code_val,
                    "display": display,
                }
            ],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient}"},
        "encounter": {"reference": f"Encounter/{encounter}"},
        "performedDateTime": performed,
    }


# === PATIENTS ===
patients = [
    {
        "resourceType": "Patient",
        "id": "patient-001",
        "name": [{"family": "Smith", "given": ["John"]}],
        "gender": "male",
        "birthDate": "1960-03-15",
    },
    {
        "resourceType": "Patient",
        "id": "patient-002",
        "name": [{"family": "Doe", "given": ["Jane"]}],
        "gender": "female",
        "birthDate": "1975-08-22",
    },
    {
        "resourceType": "Patient",
        "id": "patient-003",
        "name": [{"family": "Johnson", "given": ["Robert"]}],
        "gender": "male",
        "birthDate": "1945-11-01",
    },
    {
        "resourceType": "Patient",
        "id": "patient-004",
        "name": [{"family": "Garcia", "given": ["Maria"]}],
        "gender": "female",
        "birthDate": "1988-04-10",
    },
    {
        "resourceType": "Patient",
        "id": "patient-005",
        "name": [{"family": "Chen", "given": ["William"]}],
        "gender": "male",
        "birthDate": "1952-07-30",
    },
]

# === LOCATIONS ===
locations = [
    {
        "resourceType": "Location",
        "id": "loc-icu-01",
        "name": "Medical Intensive Care Unit",
        "status": "active",
        "mode": "instance",
        "type": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": "ICU",
                        "display": "Intensive care unit",
                    }
                ]
            }
        ],
    },
    {
        "resourceType": "Location",
        "id": "loc-er-01",
        "name": "Emergency Department",
        "status": "active",
        "mode": "instance",
        "type": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": "ER",
                        "display": "Emergency room",
                    }
                ]
            }
        ],
    },
    {
        "resourceType": "Location",
        "id": "loc-ward-01",
        "name": "General Medicine Ward",
        "status": "active",
        "mode": "instance",
        "type": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": "HU",
                        "display": "Hospital unit",
                    }
                ]
            }
        ],
    },
]

# === ENCOUNTERS ===
encounters = [
    make_enc("enc-001", "patient-001", "loc-icu-01",
             "2023-01-15T08:00:00Z", "2023-01-20T14:00:00Z"),
    make_enc("enc-002", "patient-001", "loc-ward-01",
             "2023-06-01T10:00:00Z", "2023-06-05T16:00:00Z"),
    make_enc("enc-003", "patient-002", "loc-er-01",
             "2023-03-10T14:00:00Z", "2023-03-12T11:00:00Z",
             "EMER", "emergency"),
    make_enc("enc-004", "patient-003", "loc-icu-01",
             "2023-02-01T09:00:00Z", "2023-02-28T15:00:00Z"),
    make_enc("enc-005", "patient-003", "loc-ward-01",
             "2023-07-15T08:00:00Z", "2023-07-20T12:00:00Z"),
    make_enc("enc-006", "patient-004", "loc-er-01",
             "2023-04-01T16:00:00Z", "2023-04-03T10:00:00Z",
             "EMER", "emergency"),
    make_enc("enc-007", "patient-005", "loc-icu-01",
             "2023-05-10T07:00:00Z", "2023-05-25T18:00:00Z"),
    # TEMPORAL VIOLATION: start > end
    make_enc("enc-008", "patient-005", "loc-ward-01",
             "2023-09-01T08:00:00Z", "2023-08-25T12:00:00Z"),
]

# === OBSERVATIONS ===
observations = [
    # Patient-001, enc-001 (6 obs including BP)
    make_obs("obs-001", "8867-4", "Heart rate", 72, "/min",
             "patient-001", "enc-001", "2023-01-15T10:00:00Z"),
    make_obs("obs-002", "8867-4", "Heart rate", 80, "/min",
             "patient-001", "enc-001", "2023-01-16T10:00:00Z"),
    make_obs("obs-003", "8310-5", "Body temperature", 37.2, "Cel",
             "patient-001", "enc-001", "2023-01-15T10:30:00Z"),
    make_obs("obs-004", "2160-0", "Creatinine", 1.1, "mg/dL",
             "patient-001", "enc-001", "2023-01-15T12:00:00Z"),
    make_obs("obs-005", "2160-0", "Creatinine", 0.9, "mg/dL",
             "patient-001", "enc-001", "2023-01-17T08:00:00Z"),
    make_bp("obs-bp-001", 130, 85,
            "patient-001", "enc-001", "2023-01-15T10:00:00Z"),
    # Patient-001, enc-002 (2 obs)
    make_obs("obs-006", "8867-4", "Heart rate", 68, "/min",
             "patient-001", "enc-002", "2023-06-01T14:00:00Z"),
    make_obs("obs-007", "718-7", "Hemoglobin", 14.2, "g/dL",
             "patient-001", "enc-002", "2023-06-02T08:00:00Z"),
    # Patient-002, enc-003 (3 obs)
    make_obs("obs-008", "8867-4", "Heart rate", 95, "/min",
             "patient-002", "enc-003", "2023-03-10T16:00:00Z"),
    make_obs("obs-009", "8310-5", "Body temperature", 38.8, "Cel",
             "patient-002", "enc-003", "2023-03-10T16:30:00Z"),
    make_obs("obs-010", "718-7", "Hemoglobin", 11.5, "g/dL",
             "patient-002", "enc-003", "2023-03-11T06:00:00Z"),
    # Patient-003, enc-004 (6 obs including BP)
    make_obs("obs-011", "8867-4", "Heart rate", 88, "/min",
             "patient-003", "enc-004", "2023-02-01T12:00:00Z"),
    make_obs("obs-012", "2160-0", "Creatinine", 2.3, "mg/dL",
             "patient-003", "enc-004", "2023-02-02T08:00:00Z"),
    make_obs("obs-013", "2160-0", "Creatinine", 2.1, "mg/dL",
             "patient-003", "enc-004", "2023-02-10T08:00:00Z"),
    make_obs("obs-014", "2160-0", "Creatinine", 1.8, "mg/dL",
             "patient-003", "enc-004", "2023-02-20T08:00:00Z"),
    make_obs("obs-015", "33914-3", "Glomerular filtration rate", 28, "mL/min",
             "patient-003", "enc-004", "2023-02-02T08:30:00Z"),
    make_bp("obs-bp-002", 155, 95,
            "patient-003", "enc-004", "2023-02-01T12:30:00Z"),
    # Patient-003, enc-005 (2 obs)
    make_obs("obs-016", "2160-0", "Creatinine", 1.5, "mg/dL",
             "patient-003", "enc-005", "2023-07-16T08:00:00Z"),
    make_obs("obs-017", "8867-4", "Heart rate", 76, "/min",
             "patient-003", "enc-005", "2023-07-15T10:00:00Z"),
    # Patient-004, enc-006 (3 obs)
    make_obs("obs-018", "8867-4", "Heart rate", 110, "/min",
             "patient-004", "enc-006", "2023-04-01T18:00:00Z"),
    make_obs("obs-019", "8310-5", "Body temperature", 39.1, "Cel",
             "patient-004", "enc-006", "2023-04-01T18:30:00Z"),
    make_obs("obs-020", "4548-4", "Hemoglobin A1c", 7.2, "%",
             "patient-004", "enc-006", "2023-04-02T06:00:00Z"),
    # Patient-005, enc-007 (4 obs)
    make_obs("obs-021", "8867-4", "Heart rate", 92, "/min",
             "patient-005", "enc-007", "2023-05-10T09:00:00Z"),
    make_obs("obs-022", "2160-0", "Creatinine", 3.5, "mg/dL",
             "patient-005", "enc-007", "2023-05-11T08:00:00Z"),
    make_obs("obs-023", "2160-0", "Creatinine", 3.2, "mg/dL",
             "patient-005", "enc-007", "2023-05-15T08:00:00Z"),
    make_obs("obs-024", "33914-3", "Glomerular filtration rate", 15, "mL/min",
             "patient-005", "enc-007", "2023-05-11T08:30:00Z"),
    # DANGLING REFERENCE: patient-999 does not exist
    make_obs("obs-dangling", "8867-4", "Heart rate", 75, "/min",
             "patient-999", "enc-001", "2023-01-01T10:00:00Z"),
]

# === MEDICATIONS ===
medications = [
    {
        "resourceType": "Medication",
        "id": "med-001",
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "161",
                    "display": "Acetaminophen",
                }
            ],
            "text": "Acetaminophen",
        },
    },
    {
        "resourceType": "Medication",
        "id": "med-002",
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "5224",
                    "display": "Heparin Sodium",
                }
            ],
            "text": "Heparin Sodium",
        },
    },
    {
        "resourceType": "Medication",
        "id": "med-003",
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "6058",
                    "display": "Insulin Regular",
                }
            ],
            "text": "Insulin Regular",
        },
    },
    {
        "resourceType": "Medication",
        "id": "med-004",
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "1191",
                    "display": "Aspirin",
                }
            ],
            "text": "Aspirin",
        },
    },
    {
        "resourceType": "Medication",
        "id": "med-005",
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "6809",
                    "display": "Metformin",
                }
            ],
            "text": "Metformin",
        },
    },
]

# === MEDICATION REQUESTS ===
medication_requests = [
    make_medreq("medreq-001", "patient-001", "enc-001", "med-001",
                "2023-01-15T09:00:00Z"),
    make_medreq("medreq-002", "patient-001", "enc-001", "med-002",
                "2023-01-16T08:00:00Z"),
    make_medreq("medreq-003", "patient-001", "enc-002", "med-004",
                "2023-06-02T10:00:00Z"),
    make_medreq("medreq-004", "patient-002", "enc-003", "med-001",
                "2023-03-10T15:00:00Z"),
    make_medreq("medreq-005", "patient-003", "enc-004", "med-002",
                "2023-02-01T10:00:00Z"),
    make_medreq("medreq-006", "patient-003", "enc-004", "med-003",
                "2023-02-05T09:00:00Z"),
    make_medreq("medreq-007", "patient-004", "enc-006", "med-005",
                "2023-04-01T17:00:00Z"),
    make_medreq("medreq-008", "patient-005", "enc-007", "med-002",
                "2023-05-10T08:00:00Z"),
    # DANGLING REFERENCE: med-999 does not exist
    make_medreq("medreq-dangling", "patient-001", "enc-001", "med-999",
                "2023-01-18T10:00:00Z"),
]

# === CONDITIONS ===
conditions = [
    make_cond("cond-001", "I10", "Essential hypertension",
              "patient-001", "enc-001"),
    make_cond("cond-002", "E11.9", "Type 2 diabetes mellitus without complications",
              "patient-001", "enc-002"),
    make_cond("cond-003", "K35.80", "Unspecified acute appendicitis without abscess",
              "patient-002", "enc-003"),
    make_cond("cond-004", "N18.4", "Chronic kidney disease, stage 4",
              "patient-003", "enc-004"),
    make_cond("cond-005", "I50.9", "Heart failure, unspecified",
              "patient-003", "enc-004"),
    make_cond("cond-006", "E11.9", "Type 2 diabetes mellitus without complications",
              "patient-004", "enc-006"),
    make_cond("cond-007", "N18.6", "End stage renal disease",
              "patient-005", "enc-007"),
    make_cond("cond-008", "I48.91", "Unspecified atrial fibrillation",
              "patient-005", "enc-007"),
]

# === PROCEDURES ===
procedures = [
    make_proc("proc-001", "02HV33Z", "Central venous catheter placement",
              "patient-001", "enc-001", "2023-01-15T11:00:00Z"),
    make_proc("proc-002", "30233N1", "Transfusion of nonautologous red blood cells",
              "patient-001", "enc-001", "2023-01-17T14:00:00Z"),
    make_proc("proc-003", "5A1D70Z", "Hemodialysis, intermittent",
              "patient-003", "enc-004", "2023-02-03T08:00:00Z"),
    make_proc("proc-004", "5A1D70Z", "Hemodialysis, intermittent",
              "patient-003", "enc-004", "2023-02-10T08:00:00Z"),
    make_proc("proc-005", "02HV33Z", "Central venous catheter placement",
              "patient-005", "enc-007", "2023-05-10T10:00:00Z"),
    make_proc("proc-006", "5A1D70Z", "Hemodialysis, intermittent",
              "patient-005", "enc-007", "2023-05-12T08:00:00Z"),
]


# === WRITE ALL FILES ===
write_ndjson("Patient.ndjson", patients)
write_ndjson("Location.ndjson", locations)
write_ndjson("Encounter.ndjson", encounters)
write_ndjson("Observation.ndjson", observations)
write_ndjson("Medication.ndjson", medications)
write_ndjson("MedicationRequest.ndjson", medication_requests)
write_ndjson("Condition.ndjson", conditions)
write_ndjson("Procedure.ndjson", procedures)

print(f"Generated FHIR R4 NDJSON data in {OUTPUT}/")
print(f"  Patients: {len(patients)}")
print(f"  Locations: {len(locations)}")
print(f"  Encounters: {len(encounters)}")
print(f"  Observations: {len(observations)}")
print(f"  Medications: {len(medications)}")
print(f"  MedicationRequests: {len(medication_requests)}")
print(f"  Conditions: {len(conditions)}")
print(f"  Procedures: {len(procedures)}")
