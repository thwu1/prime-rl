A C compiler conformance test suite in `/app/` contains 12 self-checking test programs in `/app/tests/` and a test harness at `/app/harness.h`. Each test uses `TEST_INIT`, `TEST_VERIFY`, and `TEST_RESULT` macros and compiles with `gcc` and `clang` using `-std=c11 -I/app` at `-O0`, `-O2`, and `-O3`, printing `PASS` on stdout with exit code 0 when correct.

Several tests are defective. Defects fall into three categories: incorrect expected values from misunderstandings of C standard semantics (`"wrong_expectation"`), reliance on undefined behavior that compilers exploit at higher optimization levels (`"undefined_behavior"`), and dependence on behavior the C standard designates as implementation-defined (`"implementation_defined"`). Some defects are latent — passing on this platform but relying on guarantees the standard does not provide.

Analyze every test. Fix all defective tests in `/app/tests/` so they pass with both compilers at all three optimization levels. Preserve each test's coverage intent: replace UB with well-defined alternatives, correct wrong expected values, and make implementation-defined assumptions portable.

Write three new conformance tests specified in `/app/new_tests.txt` and place them in `/app/tests/`.

Generate `/app/analysis.json` with the following structure. The `"defects"` array must classify every defective test. The `"all_results"` object must cover all 15 final test files (12 original + 3 new) across every compiler/optimization-level combination.

```json
{
  "defects": [
    {
      "file": "<test_file>",
      "category": "undefined_behavior|wrong_expectation|implementation_defined",
      "description": "<root cause with standard citation>",
      "standard_ref": "<ISO C section>",
      "fix_applied": "<change and rationale>"
    }
  ],
  "all_results": {
    "<test_file>": {
      "gcc_O0": "pass", "gcc_O2": "pass", "gcc_O3": "pass",
      "clang_O0": "pass", "clang_O2": "pass", "clang_O3": "pass"
    }
  }
}
```