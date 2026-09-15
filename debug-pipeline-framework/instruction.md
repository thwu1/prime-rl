The PipeWeave data pipeline framework at `/app/pipeweave/` contains latent defects distributed across its modules. A test suite at `/app/test_suite.py` exercises the framework — some tests pass, some fail. Failing tests may share root causes or be triggered by independent defects; your analysis must distinguish these cases.

Build a complete fault localization and diagnostic pipeline, perform root-cause clustering analysis, and repair all defects. When complete, all deliverables below must be in place.

## `/app/fl_tool.py` — Fault Localization Module

A Python module exposing:

- `compute_ochiai(ef, ep, nf, np_count)` → float
- `compute_tarantula(ef, ep, nf, np_count)` → float
- `compute_dstar(ef, ep, nf, np_count, star=2)` → float
- `cluster_faults(coverage_matrix, rankings, threshold=0.6)` → dict

The SBFL metrics implement their standard formulas from the fault localization research literature. Parameters: `ef`/`ep` = number of failing/passing tests executing the line; `nf`/`np_count` = failing/passing tests NOT executing the line. All three return 0.0 when ef=0. Ochiai and Tarantula return 0.0 on zero denominator. D* returns `float('inf')` when `nf + ep == 0` and `ef > 0`.

`cluster_faults` performs root-cause clustering: for every line with nonzero suspiciousness, compute the set of failing tests that execute it. Build an undirected graph where an edge connects two lines whose failing-test sets have Jaccard index ≥ `threshold`. Each connected component of this graph forms one cluster. Return format:

```json
{
  "method": "jaccard",
  "threshold": <float>,
  "num_clusters": <int>,
  "clusters": [
    {
      "id": <int>,
      "lines": [{"file": "<relpath>", "line": <int>, "score": <float>}],
      "failing_tests": ["<test_id>", ...],
      "modules_involved": ["<relpath>", ...]
    }
  ]
}
```

Each cluster's `failing_tests` is the union of failing tests across its lines. `modules_involved` lists distinct source files containing the cluster's lines. Clusters sorted by maximum suspiciousness descending.

## `/app/coverage_matrix.json`

Per-test line-level coverage collected against the **original buggy code** (before fixes):

```json
{"tests": {"<test_id>": {"passed": <bool>, "covered_lines": {"<relpath>": [<line_nums>]}}}}
```

All tests included (20+, ≥5 passing, ≥10 failing). Paths relative to `/app/`. Coverage spanning ≥3 pipeweave source modules.

## `/app/fl_results.json`

Ochiai suspiciousness rankings from the **buggy code**:

```json
{"formula": "ochiai", "rankings": {"<relpath>": [{"line": <int>, "score": <float>, "ef": <int>, "ep": <int>, "nf": <int>, "np": <int>}]}}
```

Per-file rankings sorted descending by score. Paths relative to `/app/`. Spectrum counts consistent with coverage matrix (`ef + nf` = total failing, `ep + np` = total passing, per-line counts matching coverage). At least 4 buggy modules ranked, ≥10 nonzero-suspiciousness lines, ≥5 scoring above 0.3.

## `/app/fault_clusters.json`

Output of `cluster_faults()` on buggy-code coverage and rankings. At least 3 clusters. No cross-cluster line pair may have failing-test-set Jaccard ≥ the stated threshold. Threshold must be in [0.5, 0.8].

## Bug Repairs

All defects fixed so `python3 -m pytest /app/test_suite.py -v` passes with zero failures.