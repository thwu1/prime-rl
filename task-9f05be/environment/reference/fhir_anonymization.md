# FHIR Data Anonymization — Algorithm Reference

## Configuration Format

The configuration is JSON with these sections:

- `fhirVersion`: FHIR version (e.g., "R4")
- `fhirPathRules`: Ordered list of anonymization rules. Rules are executed in the order they appear.
- `parameters`: Global parameters affecting algorithm behavior

### FHIRPath Rules

Each rule has a `path` and a `method`. Supported path patterns:

| Pattern | Example | Meaning |
|---------|---------|---------|
| `ResourceType.field` | `Resource.id` | Direct field. `Resource` matches any resource type. |
| `ResourceType.field.subfield` | `Bundle.entry.fullUrl` | Nested field path |
| `nodesByType('TypeName')` | `nodesByType('date')` | All descendant nodes of the given FHIR type |
| `nodesByType('TypeName').subfield` | `nodesByType('Reference').reference` | Sub-field within typed nodes |

**Important**: `nodesByType` returns descendants of the specified type but **excludes nodes inside Bundle entries and contained resource lists**. Each Bundle entry and each contained resource is processed independently as its own resource.

### Parameters

| Parameter | Description |
|-----------|-------------|
| `cryptoHashKey` | Key for HMAC-SHA256 hashing |
| `dateShiftKey` | Key for date-shift offset computation |
| `dateShiftScope` | Scope for date-shift prefix: `resource` (default), `file`, or `folder` |
| `enablePartialAgesForRedact` | If true, only redact dates indicating age > 89 |
| `enablePartialDatesForRedact` | If true, partial dates keep year instead of full removal |

## Anonymization Methods

### keep
Preserve the value unchanged. When a `keep` rule targets a sub-element (e.g., `nodesByType('Address').state`), that sub-element survives even if the parent type is later redacted.

### redact
Remove the element entirely. For complex types, remove all content — but sub-elements protected by an earlier `keep` rule are preserved.

### cryptoHash
Transform using HMAC-SHA256 with `cryptoHashKey`. Output is a lowercase hex string (64 chars).

**Reference handling**: When applied to `nodesByType('Reference').reference`, only the ID portion of the reference is hashed. The structural prefix and suffix are preserved:
- `Patient/abc` → `Patient/{hash(abc)}`
- `#p1` → `#{hash(p1)}`
- `http://host/fhir/Patient/abc/_history/2` → `http://host/fhir/Patient/{hash(abc)}/_history/2`
- `urn:uuid:xxx` → `urn:uuid:{hash(xxx)}`
- `#` (empty fragment) → `#` (unchanged)

### dateShift
Shift date/dateTime/instant values by a deterministic offset derived from the resource ID.

**Offset computation** (when `dateShiftScope` is `resource`):
1. Combine: `resourceId + dateShiftKey`
2. Compute SHA-256 hash of the UTF-8 encoded combined string
3. Interpret the first 4 bytes as a little-endian unsigned 32-bit integer
4. Offset = `(uint32_value % 101) - 50`, yielding a value in [-50, +50]

**Date processing rules**:
- Full date (YYYY-MM-DD): shift by offset days
- Partial date (YYYY-MM or YYYY): cannot be shifted — if `enablePartialDatesForRedact` is true, keep year only; otherwise remove entirely
- dateTime/instant: shift the date portion, **zero out the time** (set to 00:00:00), **preserve the timezone**
- If `enablePartialAgesForRedact` is true and the date indicates age > 89: **fully redact** (remove) regardless of format

## Processing Order

1. Parse all rules from configuration
2. For each resource (including contained resources processed independently):
   a. Identify elements protected by `keep` rules
   b. Apply remaining rules in config order
   c. Elements not matched by any rule are left unchanged
   d. Elements already processed by an earlier rule are skipped

## Bundle Processing

Process each `entry[].resource` as an independent resource. Bundle-level rules (e.g., `Bundle.entry.fullUrl` redact) apply to the Bundle structure itself.

## Contained Resource Processing

Resources in the `contained` array are anonymized independently — each is processed as a standalone resource with its own rule evaluation scope. The parent resource's `nodesByType` rules do not traverse into contained resources.
