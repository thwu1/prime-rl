# FHIR Anonymization Algorithm Specification

This document specifies the exact algorithms for each anonymization method referenced in config.json. Implementations must match these algorithms precisely to produce deterministic, verifiable output.

## CryptoHash Method

- Algorithm: HMAC-SHA256
- Key: `parameters.cryptoHashKey` from config
- Input: the original string value (UTF-8 encoded)
- Output: lowercase hex-encoded digest (64 characters)
- Formula: `hmac_sha256(key_bytes, value_bytes).hex()`

Applied to:
- Resource IDs: hash the original ID string
- Identifier values: hash the original value string
- References: after hashing all resource IDs, update every `reference` field of the form `ResourceType/originalId` to `ResourceType/hashedId`

## Reference Update Rules

- Parse reference strings matching the pattern `ResourceType/id`
- Replace the id portion with its HMAC-SHA256 hash (using cryptoHashKey)
- Preserve the ResourceType prefix
- Remove the `display` field from any reference object (may contain PHI)
- All references within the bundle must be updated consistently: every occurrence of a given resource ID must hash to the same value

## DateShift Method

Deterministic date shifting using HMAC-based offset derivation per resource scope:

1. Compute: `h = HMAC-SHA256(dateShiftKey_bytes, originalResourceId_bytes)`
2. Take first 4 bytes of `h` as an unsigned 32-bit big-endian integer: `n`
3. Compute offset: `offset = (n % (2 * dateShiftRange + 1)) - dateShiftRange`
4. Result is the offset in days (may be negative)

Apply this offset to all date, dateTime, and instant values within that resource:
- For date values (YYYY-MM-DD): shift the date by `offset` days
- For dateTime/instant values (YYYY-MM-DDThh:mm:ss...): shift only the date portion, preserve time and timezone
- The `originalResourceId` used for offset computation is the resource's ID **before** hashing

### Special Case: Patients Over 89

If `enablePartialAgesForRedact` is true (as configured), check each Patient's age at reference date 2024-06-01. If the patient is over 89 years old, their `birthDate` must be **redacted** (removed) rather than date-shifted, per HIPAA Safe Harbor requirements.

## Redact Method

Remove the element's value:
- For HumanName objects: remove `family`, `given`, `prefix`, `suffix`, `text` fields
- For ContactPoint objects: remove `value` field
- For Resource.text (Narrative): remove the entire `text` element from the resource
- Reference `display` fields: remove (handled during reference update)

## Generalize Method (Postal Codes)

Per HIPAA Safe Harbor geographic data requirements:
1. Extract the first 3 digits of the postal code
2. If those 3 digits appear in `restrictedZipCodeTabulationAreas` (populations < 20,000): replace entire postal code with "00000"
3. Otherwise: keep first 3 digits, replace remaining with zeros to form a 5-digit code (e.g., "98004" -> "98000")

## Keep Method

Retain the value unchanged. Applied to Address.state and Address.country.

## Security Labels

Add HIPAA anonymization security labels to each resource's `meta.security` array:
- `{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", "code": "REDACTED", "display": "redacted"}`
- `{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue", "code": "CRYTOHASH", "display": "cryptographic hash function"}`
- `{"code": "PERTURBED", "display": "exact value is replaced with another exact value"}`
