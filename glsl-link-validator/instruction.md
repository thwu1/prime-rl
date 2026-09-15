A GLSL ES 3.00 shader link-time conformance validation pipeline at `/app/` is failing 9 of its 16 test cases. The pipeline consists of:

- `/app/glsl_link_validator.py` — Python link validator; invoked as `python3 glsl_link_validator.py <vert> <frag>`, outputs JSON to stdout: `{"valid": <bool>, "errors": [{"category": "<TYPE>", "variable": "<name>"}, ...]}`
- `/app/run_tests.py` — Test harness that runs the validator against shader pairs defined in `/app/test_harness/manifest.json`
- `/app/test_harness/shaders/` — Vertex/fragment shader pairs for each test case
- `/app/spec/linking_rules.md` — GLSL ES 3.00 specification excerpts for linking rules
- `glslangValidator` — Reference GLSL compiler available on the system

Failures may originate from defects in the validator code, incorrect expected values in the test manifest, or both. For each of the 9 failures, determine which component is at fault by reasoning against the spec and the reference compiler, then apply the correct fix to that component. The validator will be tested against novel shader pairs (not in the original suite) that exercise each corrected behavior with both valid and invalid inputs.

After repairing the pipeline, produce `/app/diagnostic_report.json` classifying every defect found:

```json
{
  "validator_bugs": <count of validator-sourced defects>,
  "manifest_errors": <count of manifest-sourced defects>,
  "defects": [
    {
      "source": "validator" or "manifest",
      "affected_cases": ["case_XX", ...],
      "root_cause": "<what is wrong>",
      "fix_applied": "<what was changed>"
    }
  ]
}
```

Each distinct defect must have its own entry. The `validator_bugs` and `manifest_errors` counts must match the number of entries with corresponding `source` values.

**Success criteria**: `python3 /app/run_tests.py` exits 0 (all 16 cases pass) and `/app/diagnostic_report.json` passes schema and content validation.