Three ETSI TTCN-3 source files from a SIP (RFC 3261) conformance test suite are at `/app/ttcn3/`:

- `SIP_Registration.ttcn` -- testcase definitions for SIP registration behavior
- `SIP_CallControl.ttcn` -- testcase definitions for SIP call control behavior
- `SIP_MainModule.ttcn` -- control block that schedules test execution via guard functions

TTCN-3 is a specialized testing language defined by ETSI ES 201 873. In this suite, each `testcase` declaration includes a `with { extension "..." }` block carrying metadata (Preconditions, Description, Reference to RFC 3261 sections, FailCause, InconcCause). The `control {}` block in the MainModule conditionally executes test cases using boolean guard functions whose names encode the target testcase (e.g. `runRGRTV001()` guards `SIP_RG_RT_V_001`, `runCCPRMPRQV001()` guards `SIP_CC_PR_MP_RQ_V_001`). The naming convention maps each pair of uppercase letters in the guard abbreviation to an underscore-separated segment in the testcase name, followed by a behavior indicator (`V`/`I`/`TI`/`SM`/`O`) and a 3-digit number.

Write a static analysis tool that produces `/app/analysis_results.json` with the following structure:

**`testcase_definitions`** -- For each module (by module name) and total, count unique `testcase <NAME>(` declarations.

**`control_block`** -- From the `control { }` block in `SIP_MainModule.ttcn`:
- `active_executions`: count of uncommented `execute()` calls.
- `voided_testcases`: sorted list of testcase names appearing in commented-out `execute()` calls (both `/* */` block comments and `//` line comments), considering only comments within the control block (not the file header).

**`defects`** -- Cross-reference guard function names with executed testcase names:
- `guard_mismatches`: list of entries `{guard_function, executed_testcase, expected_testcase, defect_type}` where the derived expected testcase differs from the actually executed one. Classify `defect_type` as `number_mismatch`, `behavior_type_mismatch`, or `cross_group_mismatch`.
- `duplicate_guards`: list of entries `{guard_function, testcases: [...]}` where the same guard function appears for multiple `execute()` calls.
- `total_defect_count`: sum of guard_mismatches and duplicate_guards entries.

**`rfc_coverage`** -- Extract `Reference` fields from `with { extension "Reference: ..." }` blocks. Parse out RFC 3261 section numbers (dotted decimal like `10.2`, `8.1.1.3`) and map each section to a sorted list of testcase names that reference it.