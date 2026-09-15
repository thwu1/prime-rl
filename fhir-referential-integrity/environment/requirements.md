# HIPAA Safe Harbor De-Identification Requirements

## Compliance Scope

This dataset must be de-identified per HIPAA Safe Harbor Method §164.514(b)(2)(i), covering identifiers (A) through (Q). Map each identifier type to FHIR R4 element types and apply the appropriate anonymization method.

## Anonymization Parameters

These values must be used for deterministic, verifiable output:

| Parameter | Value |
|---|---|
| cryptoHashKey | `hipaa-safe-harbor-2024` |
| dateShiftKey | `date-shift-key-2024` |
| dateShiftRange | 50 |
| dateShiftScope | `resource` |
| referenceDate (for age) | `2024-06-01` |

### Restricted Zip Code Tabulation Areas (population < 20,000)

`036`, `059`, `063`, `102`, `203`, `556`, `692`, `790`, `821`, `823`, `830`, `831`, `878`, `879`, `884`, `890`, `893`

## Algorithm Properties

### CryptoHash

HMAC-SHA256 with `cryptoHashKey` as the HMAC key and the plaintext value (UTF-8) as the message. Output: lowercase hex digest (64 characters).

For FHIR reference strings of the form `ResourceType/id`, only the `id` portion is hashed; the `ResourceType/` prefix is preserved. The `display` field on reference objects must be removed (potential PHI leakage).

### DateShift

Deterministic per-resource: compute `HMAC-SHA256(dateShiftKey, originalResourceId)`, interpret the first 4 bytes as a big-endian unsigned 32-bit integer `n`, then `offset = (n mod (2 × dateShiftRange + 1)) − dateShiftRange`. Apply this offset in days to all date/dateTime/instant values within that resource. Use the resource's original (pre-hash) ID.

### Postal Code Generalization

Extract the 3-digit prefix. If it appears in the restricted tabulation areas list, replace the entire code with `00000`. Otherwise, keep the 3-digit prefix and zero-fill to 5 digits.

### Patient Age Over 89

If a Patient's age exceeds 89 years at the reference date, their `birthDate` must be entirely removed rather than date-shifted.

## Configuration Format

The anonymization configuration must follow the Microsoft FHIR Anonymizer JSON schema:

```json
{
  "fhirVersion": "R4",
  "processingErrors": "raise",
  "fhirPathRules": [
    {"path": "<FHIRPath expression>", "method": "<method>"},
    ...
  ],
  "parameters": { ... }
}
```

Rules are evaluated in declaration order. Available FHIRPath extension methods:
- `nodesByType('TypeName')` — selects all descendant nodes of a given FHIR type
- `nodesByName('elementName')` — selects all descendant nodes by element name

`keep` rules for fields that must be preserved (e.g., Address.state, Organization.name) must appear **before** catch-all rules that redact or transform their parent types.

## Preservation Requirements

The following must NOT be anonymized:
- Organization names
- Clinical code text (diagnosis descriptions, medication names, procedure codes)
- Observation values and units
- Encounter status codes
- Patient gender
- Address state and country
- Coding system URIs (http://loinc.org, http://snomed.info/sct, etc.)

## Security Labels

Each anonymized resource must carry security labels in `meta.security`:
- `{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", "code": "REDACTED", "display": "redacted"}`
- `{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", "code": "CRYPTOHASH", "display": "cryptographic hash function"}`

## Compliance Validation

The compliance scanner (`validate.sh`) must independently verify the de-identified output using `jq` for structural JSON querying and `openssl` for cryptographic hash verification. This ensures validation is independent of the anonymization implementation.

The scanner must produce a JSON report at `/app/output/phi_scan.json` with these boolean fields:
- `ids_valid`: all resource IDs are properly transformed
- `references_valid`: all cross-resource references resolve correctly
- `names_clean`: no residual patient or practitioner names
- `contacts_clean`: no residual contact information (phone, email)
- `addresses_clean`: all postal codes are properly generalized
- `hash_verified`: cryptographic hashes independently verified
