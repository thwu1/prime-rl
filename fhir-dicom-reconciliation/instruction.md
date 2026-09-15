A medical imaging facility maintains patient data across two systems: a DICOM Part-10 image archive at `/app/dicom_studies/` (organized in a patient/study/series hierarchy with `.dcm` files) and a FHIR R4 Bundle at `/app/fhir_bundle.json` containing Patient and ImagingStudy resources for four patients across five imaging studies.

The DICOM archive is the authoritative source of truth. The FHIR data has drifted — inconsistencies exist at the demographic, study-metadata, series, coded-terminology, and cross-resource-reference levels. Some errors are straightforward value mismatches; others involve structural or semantic violations that require deep familiarity with both standards to detect and correct.

Produce two output files:

- `/app/output/reconciliation_report.json` — JSON with a `summary` object (including `total_inconsistencies`, `patients_analyzed`, `studies_analyzed`) and an `inconsistencies` array where each entry includes the resource type, resource ID, field name, the current FHIR value, and the correct DICOM-derived value.

- `/app/output/corrected_bundle.json` — a corrected FHIR R4 Bundle preserving all original resource IDs, with every value reconciled against DICOM ground truth, missing elements populated, and all coded elements and references structurally valid per FHIR R4.