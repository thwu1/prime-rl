`/app/dicom_files/` contains DICOM Part 10 files representing imaging studies for multiple patients across several clinical contexts (breast imaging, chest CT, PET/CT oncology, head & neck MR). `/app/fhir_resources/` contains FHIR R4 JSON resources (Patient, ImagingStudy, DiagnosticReport, Practitioner) that describe the same patients and studies.

The FHIR resources contain conformance violations at multiple levels relative to the DICOM metadata ground truth. A comprehensive audit requires understanding DICOM Information Object Definitions, Value Representations (particularly the Person Name VR with its five-component structure), coded entry sequences (AnatomicRegionSequence, ProcedureCodeSequence), DICOM-to-FHIR coding scheme designator mappings (SCT, LN, DCM -> FHIR code system URIs), and cross-resource reference integrity validation. DICOM metadata is authoritative.

`pydicom` is pre-installed for DICOM parsing.

Build a conformance audit pipeline that parses both data sources, cross-references them using standard identifier mappings (PatientID, StudyInstanceUID, AccessionNumber), detects all conformance violations across patient demographics, study/series metadata, coded terminology bindings, and cross-resource references, and produces corrected FHIR resources wrapped in a FHIR Transaction Bundle.

## Required Output

### `/app/output/reconciliation_report.json`

A JSON object with a `discrepancies` array. Each element must contain:

- `resource_type`: the FHIR resource type
- `resource_id`: the FHIR resource `id`
- `field`: the FHIR field path that is incorrect
- `fhir_value`: the current (wrong) value
- `dicom_value`: the correct value from DICOM metadata

### `/app/output/corrected/`

Corrected FHIR JSON files named `{ResourceType}-{id}.json`. Each must be a complete, valid FHIR resource with all discrepant fields fixed to match DICOM ground truth. Only produce files for resources with discrepancies.

### `/app/output/transaction_bundle.json`

A valid FHIR Transaction Bundle (`Bundle.type` = `"transaction"`) wrapping all corrected resources. Each entry must have `request.method` = `"PUT"` and `request.url` = `"{ResourceType}/{id}"`.