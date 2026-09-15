Competitive programming problems are staged at `/app/problems/`, each containing an `init.yml` configuration and test data. Contestant submissions (C++ and Python) are at `/app/submissions/<problem_id>/`. The `testlib.h` header is at `/app/testlib.h`.

Build a judge that evaluates all submissions with proper resource enforcement and writes `/app/results.jsonl` — one JSON object per line, lexicographically sorted by `submission_id`:

```json
{"submission_id": "<problem>/<file>", "problem_id": "<problem>", "verdict": "<AC|WA|RE|CE|TLE>", "score": <0.0-1.0>, "testcase_results": [{"testcase": <1-indexed>, "verdict": "<verdict>", "time_ms": <int>, "memory_kb": <int>}]}
```

Verdict priority (highest wins): CE > TLE > RE > WA > AC. CE submissions have empty `testcase_results`. TLE test cases use `-1` for `time_ms` and `memory_kb`. Flat test case lists use binary scoring; batched groups use subtask-weighted scoring.