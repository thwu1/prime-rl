# FHIR R4 Anonymization Engine — Algorithm Specification

## Overview

This document specifies the algorithms for a FHIR R4 data anonymization engine compatible with the Microsoft FHIR Anonymizer configuration format.

## Configuration Format

The configuration file is JSON with these sections:

- `fhirVersion`: Target FHIR version (e.g., "R4")
- `fhirPathRules`: Ordered list of anonymization rules
- `parameters`: Global parameters affecting algorithm behavior

Rules are processed **in the order they appear** in the configuration. Each rule has a `path` (simplified FHIRPath expression) and a `method`.

## Rule Path Syntax

The following path patterns are supported:

| Pattern | Example | Meaning |
|---------|---------|---------|
| `ResourceType.field` | `Patient.id` | Direct field on a resource |
| `ResourceType.field.subfield` | `Bundle.entry.fullUrl` | Nested field path |
| `nodesByType('TypeName')` | `nodesByType('date')` | All nodes of the given FHIR type, across all resources |
| `nodesByType('TypeName').subfield` | `nodesByType('Reference').reference` | A sub-field within all nodes of a given type |
| `ResourceType.nodesByType('TypeName').subfield` | `Patient.nodesByType('HumanName').use` | Scoped type-based match within a specific resource type |

### FHIR Type Resolution

To evaluate `nodesByType` rules, the engine must know which JSON fields correspond to which FHIR types. Key mappings for Patient and Observation:

**Patient fields:**
- `text` → Narrative, `identifier` → Identifier, `name` → HumanName
- `telecom` → ContactPoint, `address` → Address, `photo` → Attachment
- `managingOrganization` → Reference, `generalPractitioner` → Reference
- `birthDate` → date, `deceasedDateTime` → dateTime, `gender` → code
- `contact` is a BackboneElement containing: `name` → HumanName, `telecom` → ContactPoint, `address` → Address, `organization` → Reference

**Observation fields:**
- `text` → Narrative, `identifier` → Identifier
- `subject` → Reference, `encounter` → Reference, `performer` → Reference
- `effectiveDateTime` → dateTime, `effectiveInstant` → instant, `issued` → instant

## Methods

### keep

Preserve the value unchanged. When a `keep` rule targets a sub-element (e.g., `Patient.nodesByType('Address').state`), that sub-element must survive even if its parent is later processed by a `redact` rule.

### redact

Remove the element entirely. For complex types (objects/arrays), remove all content. However, any sub-elements protected by an earlier `keep` rule must be preserved. For example, if `Address.state` is kept but `Address` is redacted, the result should be an Address containing only the `state` field.

### cryptoHash

Transform the value using HMAC-SHA256:

1. Compute `HMAC-SHA256(message=inputValue, key=cryptoHashKey)` where both message and key are UTF-8 encoded
2. Output the result as a lowercase hexadecimal string (64 characters)

**Special handling for Reference fields:** When the rule targets `nodesByType('Reference').reference`, the engine must parse the reference string and hash **only the ID portion**, preserving the structural prefix and suffix:

| Reference Format | Example Input | Hashed Part | Output |
|-----------------|---------------|-------------|--------|
| Relative | `Patient/abc` | `abc` | `Patient/{hash(abc)}` |
| Fragment | `#p1` | `p1` | `#{hash(p1)}` |
| Absolute URL | `http://host/fhir/Patient/abc/_history/2` | `abc` | `http://host/fhir/Patient/{hash(abc)}/_history/2` |
| URN UUID | `urn:uuid:xxx` | `xxx` | `urn:uuid:{hash(xxx)}` |
| URN OID | `urn:oid:1.2.3` | `1.2.3` | `urn:oid:{hash(1.2.3)}` |
| Empty fragment | `#` | (none) | `#` |

This ensures referential integrity: the same resource ID always produces the same hash, regardless of where the reference appears.

### dateShift

Shift date/dateTime/instant values by a computed offset.

#### Offset Computation

If `dateShiftFixedOffsetInDays` is specified in parameters, use it directly.

Otherwise, compute the offset from the resource ID and `dateShiftKey`:

1. Concatenate `resourceId + dateShiftKey` as a UTF-8 string (use empty string if resourceId is absent)
2. Compute SHA-256 hash of the concatenated string
3. Interpret the **first 4 bytes** of the hash as a **little-endian unsigned 32-bit integer**
4. Compute: `offset = (uint32_value % 101) - 50`

This yields an offset in the range [-50, +50] days.

#### Date Processing

- **Full date (YYYY-MM-DD):** Add `offset` days to the date. Output in ISO 8601 date format.
- **Partial date (YYYY-MM or YYYY):** Cannot be shifted. Apply redaction:
  - If `enablePartialDatesForRedact` is true: keep only the year (output "YYYY")
  - If false: remove the value entirely
- **dateTime (YYYY-MM-DDThh:mm:ss±TZ):** Shift the date portion by `offset` days, **zero out the time** (set to 00:00:00), and **preserve the original timezone offset**. Example: `2023-11-20T14:30:00+00:00` shifted by +5 → `2023-11-25T00:00:00+00:00`

#### HIPAA Age > 89 Rule

If `enablePartialAgesForRedact` is true, check whether the date implies an age greater than 89 years (comparing the year against the current year). If so, the date must be **fully redacted** (removed entirely) regardless of whether it could otherwise be shifted. This applies to all date types.

## Bundle Processing

For Bundle resources, process each `entry[].resource` as an independent resource. The `Bundle.entry.fullUrl` field may be targeted by rules (typically redacted). The Bundle's own metadata (`resourceType`, `id`, `type`) is preserved.

Referential integrity is maintained automatically: because cryptoHash with the same key always produces the same output for the same input, a `Patient.id` hashed in one entry will match a `subject.reference` hashed in another entry (since both hash the same ID string "patient-001").

## Processing Order

1. Parse all rules from the configuration
2. For each resource, first identify all elements protected by `keep` rules
3. Then process remaining rules in order, applying the specified method to matching elements
4. Elements not matched by any rule are left unchanged
5. When a rule matches an element that was already processed by an earlier rule, skip it
