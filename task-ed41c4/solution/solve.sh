#!/bin/bash

set -e

# Copy the Python analytics script to /app
cp /solution/pipeline.py /app/pipeline.py

# Create the ETL pipeline script
cat > /app/run.sh << 'RUNEOF'
#!/bin/bash
set -e

mkdir -p /app/intermediate /app/output

###############################################################################
# jq extraction: FHIR Bundles -> per-resource-type NDJSON
###############################################################################

# Patients
jq -c '.entry[]? | select(.resource.resourceType == "Patient") | .resource | {
  id,
  family_name: .name[0].family,
  given_name: (.name[0].given[0] // null),
  birth_date: .birthDate,
  gender,
  managing_org_ref: (.managingOrganization.reference // null)
}' /app/data/*.json > /app/intermediate/patients.ndjson

# Organizations (top-level entries only, not contained)
jq -c '.entry[]? | select(.resource.resourceType == "Organization") | .resource | {
  id,
  name,
  type_code: (.type[0].coding[0].code // null),
  city: (.address[0].city // null),
  state: (.address[0].state // null)
}' /app/data/*.json > /app/intermediate/organizations.ndjson

# Practitioners
jq -c '.entry[]? | select(.resource.resourceType == "Practitioner") | .resource | {
  id,
  family_name: .name[0].family,
  given_name: (.name[0].given[0] // null),
  prefix: (.name[0].prefix[0] // null),
  qualification_code: (.qualification[0].code.coding[0].code // null)
}' /app/data/*.json > /app/intermediate/practitioners.ndjson

# Observations — normalize effectiveDateTime to date-only via split("T")
jq -c '.entry[]? | select(.resource.resourceType == "Observation") | .resource | {
  id,
  status,
  category_code: (.category[0].coding[0].code // null),
  loinc_code: .code.coding[0].code,
  loinc_display: .code.coding[0].display,
  subject_ref: (.subject.reference // null),
  effective_date: (.effectiveDateTime | split("T")[0]),
  value_number: (.valueQuantity.value // null),
  value_unit: (.valueQuantity.unit // null)
}' /app/data/*.json > /app/intermediate/observations.ndjson

# MedicationRequests — handle choice-type medication[x]:
#   medicationCodeableConcept -> direct coding display
#   medicationReference with #fragment -> resolve from contained array
jq -c '.entry[]? | select(.resource.resourceType == "MedicationRequest") | .resource | {
  id,
  status,
  intent,
  subject_ref: (.subject.reference // null),
  medication_display: (
    if .medicationCodeableConcept then
      .medicationCodeableConcept.coding[0].display
    elif .medicationReference then
      (.medicationReference.reference | ltrimstr("#")) as $ref |
      (.contained[]? | select(.id == $ref) | .code.coding[0].display) // null
    else
      null
    end
  )
}' /app/data/*.json > /app/intermediate/medication_requests.ndjson

# Conditions — extract CodeableConcept status codes
jq -c '.entry[]? | select(.resource.resourceType == "Condition") | .resource | {
  id,
  clinical_status: .clinicalStatus.coding[0].code,
  verification_status: .verificationStatus.coding[0].code,
  snomed_code: .code.coding[0].code,
  snomed_display: .code.coding[0].display,
  subject_ref: (.subject.reference // null)
}' /app/data/*.json > /app/intermediate/conditions.ndjson

###############################################################################
# Load into SQLite + run analytics via Python
###############################################################################

python3 /app/pipeline.py

RUNEOF

chmod +x /app/run.sh

# Execute the pipeline
bash /app/run.sh
