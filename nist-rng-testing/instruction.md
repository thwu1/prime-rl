Three binary bitstream files from different pseudorandom number generators are in `/srv/nist/data/`. Bits are packed 8 per byte, MSB first, with multiple equal-length streams concatenated sequentially. `/srv/nist/config.json` specifies stream dimensions, significance level, and which statistical tests to apply with their parameters.

Evaluate each source's randomness quality according to NIST SP 800-22 Rev. 1a. For every configured test, produce results per the format below.

Write output to `/app/results.json`:

```json
{
  "<source_filename>": {
    "<test_name>": {
      "p_values": [float, ...],
      "proportion_passing": float,
      "proportion_result": "pass" | "fail",
      "uniformity_pvalue": float,
      "uniformity_result": "pass" | "fail"
    }
  },
  "summary": {
    "<source_filename>": {
      "overall": "pass" | "fail",
      "failing_tests": ["test_name", ...]
    }
  }
}
```