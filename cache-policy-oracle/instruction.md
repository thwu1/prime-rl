The `/app/` directory contains a hybrid C/Python cache replacement policy evaluation framework modeled after the 2nd Cache Replacement Championship (CRC-2). It consists of:

- `/app/native/` — C source for a native LRU cache simulation engine (not yet compiled; the build system and source contain errors)
- `/app/native/binding.py` — Python ctypes wrapper for the native engine (contains errors)
- `/app/simulator/` — Python cache simulation core
- `/app/policies/` — Replacement policy implementations: LRU, SRRIP, DRRIP, OPT (some contain algorithmic bugs), and SHiP (skeleton with full algorithm specification, not yet implemented)
- `/app/run_eval.py` — Evaluation harness that runs all policies against all traces
- `/app/traces/` — Memory access traces with distinct workload patterns
- `/app/validation/golden_reference.json` — Expected values for validation

Produce three output files:

1. `/app/native/libcachesim.so` — The compiled, working native LRU simulation engine. When loaded via the corrected `/app/native/binding.py`, it must produce LRU hit/miss counts identical to the Python simulator on every trace.

2. `/app/results.json` — Output of `python3 /app/run_eval.py` after fixing all policy bugs and completing the SHiP implementation. Must contain correct results for all five policies (`lru`, `srrip`, `drrip`, `opt`, `ship`) across all traces, satisfying the schema and constraints in `/app/validation/golden_reference.json`.

3. `/app/policy_ranking.json` — Comparative analysis ranking practical (non-OPT) policies:

        {
          "per_trace_best": {"<trace_name>": "<policy_name>", ...},
          "overall_ranking": ["<best_policy>", ..., "<worst_policy>"],
          "champion": "<best_policy>"
        }

    `per_trace_best` maps each trace to the practical policy with the lowest miss rate. `overall_ranking` sorts practical policies by descending `geomean_miss_rate_reduction`. `champion` is the top-ranked policy.