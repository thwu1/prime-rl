Three FHIR R5 transaction processor implementations are deployed at `/app/processor_a.py`, `/app/processor_b.py`, and `/app/processor_c.py`. Each accepts a transaction Bundle and a server-state directory and produces a transaction-response Bundle and updated server state. All three use different architectural approaches and contain different conformance violations against the FHIR R5 specification. Some violations are obvious; others are subtle and only manifest through specific feature interactions.

Pre-generated output from each processor is at `/app/output_a/`, `/app/output_b/`, and `/app/output_c/` respectively.

Input data:
- `/app/data/transaction_bundle.json` -- an 11-entry transaction Bundle exercising DELETE, POST (with and without conditional operations), and PUT operations with inter-entry references.
- `/app/data/server_state/` -- initial server state as individual `{ResourceType}_{id}.json` files.

The FHIR R5 RESTful API specification is at `/app/spec/fhir_r5_restful_api.html` (readable with `w3m`).

Evaluate all three processors against the FHIR R5 specification and produce:

1. A conformance evaluation report at `/app/conformance_report.json` with the following schema:

```json
{
  "processor_a": {
    "violations": [{"category": "<operation_ordering|reference_resolution|status_codes|versioning|conditional_create|conditional_reference|other>", "description": "...", "severity": "error|warning"}],
    "conformance_score": <integer 0-100>
  },
  "processor_b": { "violations": [...], "conformance_score": ... },
  "processor_c": { "violations": [...], "conformance_score": ... },
  "comparative_analysis": {
    "superior_implementation": "<processor_a or processor_b or processor_c>",
    "architectural_strengths": {"processor_a": ["..."], "processor_b": ["..."], "processor_c": ["..."]},
    "recommendation": "..."
  }
}
```

Each violation must identify the conformance category, provide a substantive description citing the relevant FHIR R5 specification requirement, and assign a severity. Scores should reflect the number and severity of violations. The comparative analysis must identify the architecturally superior implementation and list concrete strengths of each approach.

2. A `jq`-based validation toolkit at `/app/validation/` consisting of executable shell scripts that programmatically detect FHIR conformance violations in processor output. Each check script must output a JSON object to stdout with at minimum `"status"` (`"pass"` or `"fail"`) and `"issue_count"` (integer) fields, and exit 0 for conformant / exit 1 for non-conformant. Required scripts:
   - `check_references.sh <output_dir>` -- scans all server state resources in the given output directory for unresolved `urn:uuid:` references and unresolved conditional references using `jq` recursive descent
   - `check_status_codes.sh <output_dir>` -- validates response Bundle entry status codes against FHIR R5 requirements for each HTTP method, reading the input bundle from `/app/data/transaction_bundle.json`
   - `check_versioning.sh <output_dir> <initial_state_dir>` -- verifies `meta.versionId` and `meta.lastUpdated` handling for PUT-updated resources by comparing against the initial state
   - `diff_processors.sh` (no arguments) -- outputs a JSON object with keys `processor_a`, `processor_b`, `processor_c`, each containing conformance metrics including `unresolved_urn_uuids` count

3. A correct reference implementation at `/app/processor.py` that uses the same CLI interface (`--bundle`, `--state-dir`, `--output-dir`, `--base-url`) and produces fully FHIR R5-conformant output at `/app/output/` when run against the provided input data.