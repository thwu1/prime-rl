# HL7 FHIR R4 Data Model Reference

## Bundles

A Bundle is a collection of resources, each wrapped in an `entry`:

    {
      "resourceType": "Bundle",
      "type": "collection",
      "entry": [
        {
          "fullUrl": "Patient/pat-1",
          "resource": { "resourceType": "Patient", "id": "pat-1", ... }
        }
      ]
    }

The `fullUrl` can be a relative reference (`Patient/pat-1`), an absolute URL,
or a URN (`urn:uuid:...`). Only top-level entries appear in `entry` — contained
resources are nested inside other resources and are NOT separate Bundle entries.

## Resource Structure

Every FHIR resource has a `resourceType` field and usually an `id` field.

## CodeableConcept / Coding

Many FHIR elements use the CodeableConcept structure with nested Coding arrays:

    {
      "code": {
        "coding": [
          { "system": "http://loinc.org", "code": "8867-4", "display": "Heart rate" }
        ]
      }
    }

A CodeableConcept may have multiple Coding entries (e.g., LOINC + SNOMED for
the same concept). The primary code is typically the first entry.

Elements like `clinicalStatus` and `verificationStatus` on Condition resources
also use this pattern:

    "clinicalStatus": {
      "coding": [
        { "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
          "code": "active" }
      ]
    }

## References

FHIR resources reference each other via reference objects:

    { "reference": "Patient/pat-1" }         // relative
    { "reference": "#med-1" }                 // fragment (contained)
    { "reference": "urn:uuid:..." }           // URN

- **Relative**: `ResourceType/id` (e.g., `Patient/pat-1`)
- **Fragment**: `#id` — points to a resource in the parent's `contained` array
- **URN**: `urn:uuid:...` or `urn:oid:...`

## Contained Resources

A resource may embed other resources in its `contained` array. These are
referenced via fragment references (`#id`):

    {
      "resourceType": "MedicationRequest",
      "contained": [
        {
          "resourceType": "Medication",
          "id": "med-inline",
          "code": {
            "coding": [
              { "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "code": "198440",
                "display": "Lisinopril 10 MG Oral Tablet" }
            ]
          }
        }
      ],
      "medicationReference": { "reference": "#med-inline" }
    }

To resolve a contained reference, strip the `#` prefix and search the
containing resource's `contained` array for a matching `id`.

## Choice Types (Polymorphic Elements)

FHIR uses `[x]` to denote polymorphic elements. In JSON, the concrete type
name replaces `[x]`. Only ONE variant appears per resource instance:

| FHIR Definition | JSON Key                  | Notes                        |
|-----------------|---------------------------|------------------------------|
| value[x]        | valueQuantity             | Numeric with unit            |
| value[x]        | valueString               | Plain text                   |
| value[x]        | valueCodeableConcept      | Coded value                  |
| medication[x]   | medicationReference       | Reference to Medication      |
| medication[x]   | medicationCodeableConcept | Inline coded medication      |
| effective[x]    | effectiveDateTime         | Point in time                |
| effective[x]    | effectivePeriod           | Time range (start/end)       |

### Example: medication[x]

A MedicationRequest may use EITHER:
- `medicationCodeableConcept` — an inline coded medication with direct access
  to `coding[0].display`
- `medicationReference` — a reference to a Medication resource (often
  contained via a `#id` fragment reference)

To extract the medication display name, check which variant is present and
follow the appropriate path.

## Date/Time Formats

ISO 8601 with variable precision:
- Year: `2024`
- Month: `2024-01`
- Day: `2024-01-15`
- DateTime: `2024-01-15T10:30:00Z`
- DateTime with offset: `2024-02-20T14:00:00+05:30`

When normalizing to date-only for analytics, truncate at the `T` separator.
Values without a `T` (date-only) remain unchanged.

## Patient

    {
      "resourceType": "Patient",
      "id": "pat-1",
      "name": [{"family": "Smith", "given": ["John"]}],
      "birthDate": "1990-03-15",
      "gender": "male",
      "managingOrganization": { "reference": "Organization/org-1" }
    }

- `name` is an array; `given` within each name is also an array
- Not all patients have `managingOrganization`
- Some patients have `generalPractitioner` (an array of references) instead

## Observation

    {
      "resourceType": "Observation",
      "id": "obs-1",
      "status": "final",
      "category": [{"coding": [{"system": "...", "code": "vital-signs"}]}],
      "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4",
               "display": "Heart rate"}]},
      "subject": {"reference": "Patient/pat-1"},
      "effectiveDateTime": "2024-01-15T10:30:00Z",
      "valueQuantity": {"value": 72, "unit": "beats/minute",
                        "system": "http://unitsofmeasure.org", "code": "/min"}
    }

## Organization

    {
      "resourceType": "Organization",
      "id": "org-1",
      "name": "General Hospital",
      "type": [{"coding": [{"system": "...", "code": "prov"}]}],
      "address": [{"city": "Anytown", "state": "CA"}]
    }

## Practitioner

    {
      "resourceType": "Practitioner",
      "id": "pract-1",
      "name": [{"family": "Chen", "given": ["Emily"], "prefix": ["Dr."]}],
      "qualification": [{"code": {"coding": [{"system": "...", "code": "MD"}]}}]
    }

## Condition

    {
      "resourceType": "Condition",
      "id": "cond-1",
      "clinicalStatus": {"coding": [{"system": "...", "code": "active"}]},
      "verificationStatus": {"coding": [{"system": "...", "code": "confirmed"}]},
      "code": {"coding": [{"system": "http://snomed.info/sct",
               "code": "38341003", "display": "Hypertension"}]},
      "subject": {"reference": "Patient/pat-1"}
    }

## MedicationRequest

    {
      "resourceType": "MedicationRequest",
      "id": "medreq-1",
      "status": "active",
      "intent": "order",
      "subject": {"reference": "Patient/pat-1"},
      "medicationReference": {"reference": "#med-inline"}
    }

See "Contained Resources" and "Choice Types" above for how to resolve
the medication display name.

## Quantity

    {
      "value": 72,
      "unit": "beats/minute",
      "system": "http://unitsofmeasure.org",
      "code": "/min"
    }
