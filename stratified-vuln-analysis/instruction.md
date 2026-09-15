`/app/data/experiments.json` contains 100 kernel vulnerability reproduction experiments. Each case represents the same vulnerability tested under multiple configurations of an LLM-agent system. Records include:

- `vuln_type` (uaf_df / oob / other), `subsystem` (net / netfilter / bpf / other), `is_race_condition` (bool), `commit_msg_level` (1-3), `is_post_cutoff` (bool)
- Outcomes per configuration: `baseline_run1_success`, `baseline_run2_success`, `no_gdb_success`, `no_utilities_success`, `degraded_prompt_success`, `no_commit_msg_success` (all boolean)
- `cheating_detected` (bool) -- agent manipulated kernel state via debugger to produce artificial crashes
- `baseline_run3_success` -- populated only for cases that failed both runs 1 and 2; `null` otherwise

A colleague submitted a draft analysis at `/app/data/draft_analysis.json` with methodology documented in `/app/data/draft_methodology.md`. The draft contains errors that compromise validity.

Audit the draft against the raw data, identify where the methodology is flawed, and produce a corrected analysis at `/app/results/analysis.json` conforming to the schema below. All float values rounded to 4 decimal places.

## Output schema (all keys required)

- `overall_success_rates`: map of configuration name -> success rate
- `race_condition_analysis`: keys `race_success_rate`, `nonrace_success_rate`, `odds_ratio`, `p_value`
- `vuln_type_analysis`: keys `odds_ratio`, `p_value`, `test_statistic`, `consistency_statistic`, `consistency_p_value`
- `config_comparison_tests`: map of `baseline_vs_<config>` -> `{statistic, p_value}` for each non-baseline configuration
- `convergence_analysis`: keys `run1_successes`, `run2_successes`, `union_2_runs`, `union_rate_2_runs`, `run3_additional`, `union_rate_3_runs`
- `cutoff_analysis`: keys `pre_cutoff_rate`, `post_cutoff_rate`, `odds_ratio`, `p_value`
- `subsystem_analysis`: map of subsystem -> `{n, success_rate, odds_ratio, p_value}`
- `commit_msg_analysis`: map of level as string ("1"/"2"/"3") -> `{n, success_rate}`