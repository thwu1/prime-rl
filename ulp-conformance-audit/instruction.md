A vendor has submitted math function implementations for OpenCL conformance certification. Their test results are provided as precomputed (input, output) pairs in IEEE 754 float32 hex encoding at `/app/test_data.json`. Each function has an associated ULP (Units in the Last Place) error tolerance from the OpenCL specification.

Your task: build a conformance auditor that determines which functions pass or fail their ULP tolerance.

## What you must produce

Create `/app/audit_report.json` with this structure:

```json
{
  "functions": {
    "<name>": {
      "pass": <bool>,
      "max_ulp_error": <float>,
      "num_test_cases": <int>,
      "num_exceeding_tolerance": <int>
    }
  },
  "overall_pass": <bool>,
  "functions_failing": ["<name>", ...]
}
```

## Requirements

- For each function in `/app/test_data.json`, compute the ULP error of every test case's `output_hex` against the mathematically correct (infinitely precise) result of that function applied to `input_hex`.
- Both `input_hex` and `output_hex` are IEEE 754 binary32 values encoded as 8-character uppercase hex strings.
- Reference values must be computed at higher-than-double precision to determine the correctly rounded float32 result.
- ULP error is defined as `|output - exact_reference| / ulp(exact_reference)`, where `ulp(x)` is `2^(floor(log2(|x|)) - 23)` for normal numbers. Subnormal values use a fixed ULP of `2^(-149)`.
- A function passes if its maximum ULP error across all test cases is `<= tolerance_ulp`.
- `ftz_mode` is enabled: if the mathematically correct result is a subnormal float32 (nonzero with `|x| < 2^(-126)`), an implementation output of `±0` is acceptable (0 ULP error).
- NaN outputs for NaN inputs have 0 ULP error. NaN/Inf edge cases must be handled correctly per IEEE 754 semantics.
- `max_ulp_error` should be rounded to 2 decimal places.
- `functions_failing` must be sorted alphabetically.