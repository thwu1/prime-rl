`/app/` contains a causal inference analysis system built on a custom Structural Causal Model (SCM) framework. The system constructs several test SCMs with known graph structures and linear mechanisms, then performs three types of analysis: d-separation testing on directed acyclic graphs, do-calculus Rule 2 verification, and causal effect estimation (both interventional ATE and counterfactual treatment effects).

Running `bash /app/run_analysis.sh` should produce:

- A JSON report at `/app/output/analysis_report.json`
- A completion marker at `/app/output/.completed`

The pipeline fails because three core functions raise `NotImplementedError`:

- `is_d_separated()` in `/app/graph_utils.py` — determines whether two sets of nodes are conditionally independent given a third set in a DAG
- `verify_rule2()` in `/app/do_calculus.py` — determines whether Pearl's do-calculus Rule 2 applies for a given set of variables in a DAG
- `compute_counterfactual_te()` in `/app/query_engine.py` — computes the counterfactual treatment effect conditioned on observed evidence, using the SCM's noise variables

Each function's docstring documents its precise mathematical contract and expected behavior. The existing SCM framework in `/app/scm.py`, `/app/variable.py`, and `/app/mechanism.py` provides the working infrastructure (variable management, edge structure, mechanism evaluation, interventions, noise sampling, and forward computation).

The pipeline tests d-separation on four canonical graph structures (chain, fork, collider, diamond) across 10 different (X, Y, Z) configurations. It verifies do-calculus Rule 2 applicability across 4 variable configurations spanning multiple graphs. It computes ATE and counterfactual treatment effects for 3 graphs with linear mechanisms. D-separation and Rule 2 boolean results must be mathematically correct. Treatment effect estimates must be within 0.2 of their analytical values. The report must be valid JSON parseable by `jq`. All `ate_cf_consistent` flags in the report must be `true`.

The implemented functions must produce correct results for any valid DAG input, not only the specific graphs used by the pipeline.

## Output Schema

`/app/output/analysis_report.json` must conform to the following structure:

```json
{
  "d_separation_tests": [
    {
      "graph_name": "<string>",
      "X_set": ["<string: source node names>"],
      "Y_set": ["<string: target node names>"],
      "Z_set": ["<string: conditioning node names>"],
      "result": "<boolean: true if d-separated, false otherwise>"
    }
  ],
  "do_calculus_tests": [
    {
      "graph_name": "<string>",
      "X_vars": ["<string: intervention variable names>"],
      "Z_vars": ["<string: variables whose do/observe status is tested>"],
      "Y_vars": ["<string: outcome variable names>"],
      "W_vars": ["<string: additional conditioning variable names>"],
      "applicable": "<boolean: true if Rule 2 applies>"
    }
  ],
  "causal_effects": [
    {
      "graph_name": "<string>",
      "treatment": "<string: treatment variable name>",
      "outcome": "<string: outcome variable name>",
      "ate": "<number: Average Treatment Effect estimate>",
      "counterfactual_te": "<number: Counterfactual Treatment Effect estimate>",
      "ate_cf_consistent": "<boolean: true if |ATE - CTF_TE| < 0.5>"
    }
  ],
  "timestamp": "<string: ISO 8601 timestamp>"
}
```

The `d_separation_tests` array must contain exactly 10 entries, `do_calculus_tests` exactly 4 entries, and `causal_effects` exactly 3 entries.