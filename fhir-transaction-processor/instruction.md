A FHIR R4 transaction processing engine at `/app/fhir_engine.py` is producing non-conformant output when processing clinical data integration bundles. The engine is invoked as:

```
python3 /app/fhir_engine.py <input_bundle.json> <server_state_dir> <output.json>
```

Transaction Bundles are at `/app/bundles/`. Pre-existing server state is at `/app/server_state/`.

Diagnose and fix all conformance and semantic issues in `/app/fhir_engine.py`. The engine must correctly implement FHIR R4 transaction Bundle processing per the specification, producing conformant transaction-response Bundles or OperationOutcome resources on transaction failure.

Write a conformance validator at `/app/validate_output.py` that uses FHIRPath expressions to check transaction-response Bundles against FHIR structural invariants. It takes a JSON file path argument, prints diagnostics, and exits 0 for conformant output or 1 otherwise. The `fhirpathpy` package is available for FHIRPath evaluation.