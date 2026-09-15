Build a pipeline at `/app/` that evaluates FHIR access request scenarios against Medplum-style AccessPolicy resources and produces both access decisions and a cryptographically signed audit trail.

## Reference Implementation

TypeScript source files from the Medplum FHIR platform are provided at `/app/reference/`:
- `access.ts` — Access policy matching, protected/admin resource type classification, interaction support logic
- `accesspolicy.ts` — Policy assembly and parameterized variable substitution from membership configuration
- `repo.ts` — Repository-level enforcement during read/write operations
- `access-policies.md` — Feature documentation with configuration examples

These files are the authoritative specification for expected evaluation behavior. The TypeScript code depends on the full Medplum ecosystem and cannot be executed directly, but defines the evaluation semantics, constants (e.g., the `projectAdminResourceTypes` array controlling wildcard exclusions), and logic your pipeline must replicate.

## Data

Input files at `/app/data/`:
- `capability_statement.json` — FHIR CapabilityStatement declaring server search capabilities; search parameter-to-field-path mappings are encoded as extensions (url: `http://medplum.com/fhir/StructureDefinition/search-parameter-path`) on individual `searchParam` entries within `rest[0].resource[]`. Not all search params have path mappings; only those with the extension are usable for criteria evaluation. The CapabilityStatement includes resource types beyond those needed for this task.
- `policies.json` — AccessPolicy resources with `resource` arrays defining per-type rules
- `memberships.json` — User-to-policy assignments with optional parameterized references
- `*.ndjson` — FHIR resources in Newline-Delimited JSON format (one JSON object per line), split by resource type per the FHIR Bulk Data Export convention. All `.ndjson` files in `/app/data/` must be loaded to build the resource index.
- `scenarios.json` — 35 access request scenarios to evaluate
- `audit_key.hex` — Hex-encoded 256-bit HMAC-SHA256 key for audit log signing

## Output

Produce two files:

### `/app/results.json`
JSON object mapping each scenario ID to its access decision:
```json
{
  "scenario_id": {
    "decision": "allow" | "deny",
    "hidden_fields": ["..."],
    "readonly_fields": ["..."]
  }
}
```
Field lists must be sorted. Omit `hidden_fields` and `readonly_fields` keys when not applicable.

### `/app/audit.json`
JSON object mapping each scenario ID to its HMAC-SHA256 hex digest. Each digest covers the canonical string `{scenario_id}:{decision}` signed with the key from `audit_key.hex`:
```json
{
  "s01": "a1b2c3...",
  "s02": "d4e5f6..."
}
```

Entry point: `bash /app/run_pipeline.sh`