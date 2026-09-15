# HL7 v2.5.1 ADT_A01 → FHIR R4 Mapping Specification

## HL7 v2 Message Encoding

- **Field separator**: `|` (MSH-1)
- **Encoding characters**: `^~\&` (MSH-2)
  - `^` component separator
  - `~` repetition separator
  - `\` escape character
  - `&` sub-component separator
- **Escape sequences**: `\F\` → `|`, `\S\` → `^`, `\T\` → `&`, `\R\` → `~`, `\E\` → `\`
- Trailing empty fields may be omitted. Empty fields between pipes are null.

## MSH Field Indexing

MSH-1 is the field separator character itself. When splitting on `|`, MSH-2 is the first value after the segment name. All other segments use standard 1-based indexing where field N is the Nth pipe-delimited value after the segment name.

## Output: FHIR R4 Transaction Bundle

```json
{
  "resourceType": "Bundle",
  "type": "transaction",
  "entry": [
    {
      "fullUrl": "urn:uuid:<deterministic-uuid>",
      "resource": { ... },
      "request": { "method": "POST", "url": "<ResourceType>" }
    }
  ]
}
```

Resources reference each other by `fullUrl` URN within the Bundle.

## Segment → Resource Mappings

### PID → Patient

| v2 Field | FHIR Element | Notes |
|----------|-------------|-------|
| PID.3 (CX, repeating via `~`) | Patient.identifier[] | CX.1→value, CX.4→system, CX.5→type.coding[0].code (system: `http://terminology.hl7.org/CodeSystem/v2-0203`) |
| PID.5 (XPN) | Patient.name[] | XPN.1→family, XPN.2→given[0], XPN.3→given[1], XPN.5→prefix[0], XPN.4→suffix[0] |
| PID.7 (TS) | Patient.birthDate | YYYYMMDD → YYYY-MM-DD |
| PID.8 | Patient.gender | M→male, F→female, O→other, U→unknown |
| PID.11 (XAD, repeating via `~`) | Patient.address[] | XAD.1→line[0], XAD.2→line[1], XAD.3→city, XAD.4→state, XAD.5→postalCode, XAD.6→country |
| PID.13 (XTN, repeating via `~`) | Patient.telecom[] | See XTN mapping below |
| PID.15 | Patient.communication[0].language.text | |
| PID.16 | Patient.maritalStatus | Code system: `http://terminology.hl7.org/CodeSystem/v3-MaritalStatus` |

### PV1 → Encounter

| v2 Field | FHIR Element | Notes |
|----------|-------------|-------|
| PV1.2 | Encounter.class | I→IMP, O→AMB, E→EMER, R→IMP. System: `http://terminology.hl7.org/CodeSystem/v3-ActCode` |
| PV1.7 (XCN) | Encounter.participant[] | Type code: ATND. XCN.1→identifier, XCN.2→family, XCN.3→given |
| PV1.19 | Encounter.identifier[0].value | Visit number |
| PV1.44 (TS) | Encounter.period.start | YYYYMMDDHHMMSS → YYYY-MM-DDTHH:MM:SS |

Encounter.status: set to `"in-progress"`. Encounter.subject: reference to Patient.

### NK1 → RelatedPerson (one per segment)

| v2 Field | FHIR Element | Notes |
|----------|-------------|-------|
| NK1.2 (XPN) | RelatedPerson.name[] | Same XPN mapping as PID.5 |
| NK1.3 | RelatedPerson.relationship[0] | Code system: `http://terminology.hl7.org/CodeSystem/v2-0131` |
| NK1.4 (XAD) | RelatedPerson.address[] | Same XAD mapping |
| NK1.5 (XTN) | RelatedPerson.telecom[] | Same XTN mapping |

RelatedPerson.patient: reference to Patient.

### DG1 → Condition (one per segment)

| v2 Field | FHIR Element | Notes |
|----------|-------------|-------|
| DG1.3 (CWE) | Condition.code | CWE.1→code, CWE.2→display, CWE.3→system (see coding system mapping) |
| DG1.6 | Condition.category | A/W/F → `encounter-diagnosis` (system: `http://terminology.hl7.org/CodeSystem/condition-category`) |

Condition.clinicalStatus: `active` (system: `http://terminology.hl7.org/CodeSystem/condition-clinical`).
Condition.subject: reference to Patient.

### AL1 → AllergyIntolerance (one per segment)

| v2 Field | FHIR Element | Notes |
|----------|-------------|-------|
| AL1.2 | AllergyIntolerance.category[] | DA→medication, FA→food, EA→environment |
| AL1.3 (CWE) | AllergyIntolerance.code | Same CWE mapping |
| AL1.4 | AllergyIntolerance.criticality | SV→high, MO→low, MI→low |
| AL1.5 (repeating via `~`) | AllergyIntolerance.reaction[0].manifestation[] | Each repetition → one manifestation CodeableConcept.text |
| AL1.6 (DT) | AllergyIntolerance.onsetDateTime | YYYYMMDD → YYYY-MM-DD |

AllergyIntolerance.clinicalStatus: `active`. AllergyIntolerance.patient: reference to Patient.

### IN1 → Coverage (one per segment)

| v2 Field | FHIR Element | Notes |
|----------|-------------|-------|
| IN1.2 | Coverage.identifier[].value | Plan ID |
| IN1.4 | Coverage.payor[0].display | Insurance company name |
| IN1.12 (DT) | Coverage.period.start | YYYYMMDD → YYYY-MM-DD |
| IN1.13 (DT) | Coverage.period.end | YYYYMMDD → YYYY-MM-DD |

Coverage.status: `active`. Coverage.beneficiary: reference to Patient.

## XTN (Telecom) → ContactPoint Mapping

| XTN Component | ContactPoint Element | Notes |
|--------------|---------------------|-------|
| XTN.2 | ContactPoint.use | PRN→home, WPN→work, ORN→old |
| XTN.3 | ContactPoint.system | PH→phone, CP→phone, FX→fax, Internet→email, BP→pager |
| XTN.4 | ContactPoint.value | Used when XTN.3=Internet (email address) |
| XTN.7 | ContactPoint.value | Local phone number (preferred over XTN.1) |
| XTN.1 | ContactPoint.value | Fallback if XTN.7 empty |

## Coding System URI Mapping

| v2 Name | FHIR System URI |
|---------|----------------|
| ICD-10-CM | `http://hl7.org/fhir/sid/icd-10-cm` |
| ICD-10 | `http://hl7.org/fhir/sid/icd-10` |
| RXNORM | `http://www.nlm.nih.gov/research/umls/rxnorm` |
| SNOMED | `http://snomed.info/sct` |
| LOINC | `http://loinc.org` |
| L | `http://terminology.hl7.org/CodeSystem/v2-0396` |
