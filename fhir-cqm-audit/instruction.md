A FHIR R4 server (`/app/fhir_server.py`) and patient database (`/app/patient_data.json`) are provided. Start it with `/app/start_fhir.sh` (listens on `http://localhost:8080/fhir`). The database has 6 patients with demographics, conditions (ICD-10-CM), observations (LOINC), and medications (RxNorm).

Evaluate every patient against all five CQMs below. For each care gap found, place the corrective FHIR order on the server via POST/PUT.

## Clinical Quality Measures

**CQM-1 — Uncontrolled Diabetes:** Patients with active diabetes (ICD-10 E10.x/E11.x) whose most recent HbA1c (LOINC 4548-4) >= 9.0% require a ServiceRequest for endocrinology referral.

**CQM-2 — CKD Medication Safety:** Patients with eGFR (LOINC 33914-3) < 30 mL/min on active metformin must have it discontinued (update status to "stopped" via PUT, or create a new MedicationRequest with status "stopped").

**CQM-3 — Atrial Fibrillation Anticoagulation:** Patients with atrial fibrillation (ICD-10 I48.x), CHA2DS2-VASc >= 2, and no current oral anticoagulant require a MedicationRequest for one. CHA2DS2-VASc: CHF +1, Hypertension +1, Age>=75 +2 or 65-74 +1, Diabetes +1, Stroke/TIA +2, Female +1.

**CQM-4 — Statin for Severe Hyperlipidemia:** Patients with LDL (LOINC 2089-1) > 190 mg/dL and no active statin require a MedicationRequest for statin therapy.

**CQM-5 — Nephrology Referral for Advanced CKD:** Patients with eGFR < 30 mL/min and no existing nephrology referral require a ServiceRequest for nephrology consultation.

## Deliverable

Write a JSON audit report to `/app/output/cqm_audit_report.json`:

```json
{
  "patients": [
    {
      "patient_id": "<FHIR Patient ID>",
      "patient_name": "<Family, Given>",
      "gaps_identified": [
        {
          "cqm_id": "CQM-X",
          "description": "<brief description>",
          "action": "<order created or medication stopped>",
          "fhir_resource_id": "<ID of created/updated resource>"
        }
      ]
    }
  ],
  "summary": {
    "total_patients": 6,
    "patients_with_gaps": "<count>",
    "total_gaps": "<count>"
  }
}
```