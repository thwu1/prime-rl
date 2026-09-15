# Judge Specification

## Problem Configuration (init.yml)

Each problem directory under `/app/problems/<problem_id>/` contains an `init.yml` following DMOJ conventions and a `testdata/` directory with test files.

### Flat test cases (binary, all-or-nothing scoring)

```yaml
test_cases:
- {in: testdata/1.in, out: testdata/1.out, points: 0}
- {in: testdata/2.in, out: testdata/2.out, points: 0}
time_limit: 5.0
memory_limit: 262144
checker: standard
```

When all entries have `points: 0`, scoring is binary: 1.0 if every test case is AC, else 0.0.

### Batched test cases (subtask partial scoring)

```yaml
test_cases:
- batched:
    - {in: testdata/1.in, out: testdata/1.out}
    - {in: testdata/2.in, out: testdata/2.out}
  points: 50
- batched:
    - {in: testdata/3.in, out: testdata/3.out}
    - {in: testdata/4.in, out: testdata/4.out}
  points: 50
time_limit: 5.0
memory_limit: 262144
checker: standard
```

A subtask's points are awarded only if all of its test cases are AC. Score = earned / total points.

### Fields

- `time_limit`: float, seconds
- `memory_limit`: integer, kilobytes
- `checker`: `standard` or `bridged`
- `custom_judge`: C++ source filename (required when checker is `bridged`), relative to the problem directory
- In/out paths are relative to the problem directory

## Checker Modes

### standard
Compare expected and actual output after normalizing: strip trailing whitespace per line, drop trailing empty lines, then compare line-by-line.

### bridged (testlib)
The `custom_judge` source file uses `#include "testlib.h"` (the header is at `/app/testlib.h`). Compile the checker and invoke it following the standard testlib checker protocol. Exit code 0 = AC, non-zero = WA.

## Compilation

- C++ submissions must be compiled before execution. Compilation failure = CE verdict, empty testcase_results, score 0.0.
- Python submissions are executed directly with `python3`.

## Execution and Resource Enforcement

Each test case must be executed with resource limits enforced as specified in the problem's `init.yml`. The system provides `prlimit` (util-linux) and GNU `/usr/bin/time` for resource control and measurement.

- **CPU time**: Submissions exceeding `time_limit` seconds of CPU time must be terminated.
- **Virtual memory**: Submissions must be constrained to `memory_limit` kilobytes of virtual address space.
- A wall-clock safeguard must prevent hung processes.

Per-test-case resource measurements:
- `time_ms`: wall-clock execution time in milliseconds (integer >= 0), or -1 for TLE
- `memory_kb`: peak resident set size in kilobytes (integer > 0), or -1 for TLE

### Verdict Classification (per test case, in priority order)
1. Process terminated due to CPU time limit or wall-clock timeout → **TLE** (`time_ms = -1`, `memory_kb = -1`)
2. Process exits with non-zero status (not from resource enforcement) → **RE**
3. Checker rejects output → **WA**
4. Checker accepts output → **AC**

### Overall Verdict
- CE if compilation fails
- Otherwise the highest-priority non-AC verdict across all test cases, or AC if all pass

All test cases must be evaluated; do not short-circuit.

## Output Schema (results.jsonl)

One JSON object per line, sorted lexicographically by `submission_id`:

```json
{
  "submission_id": "<problem_id>/<filename>",
  "problem_id": "<problem_id>",
  "verdict": "AC|WA|RE|TLE|CE",
  "score": 0.0,
  "testcase_results": [
    {"testcase": 1, "verdict": "AC", "time_ms": 15, "memory_kb": 2048},
    ...
  ]
}
```

- `time_ms`: wall-clock milliseconds (non-negative integer), or -1 for TLE
- `memory_kb`: peak resident set size in kbytes (positive integer), or -1 for TLE
- CE submissions have empty `testcase_results` array
