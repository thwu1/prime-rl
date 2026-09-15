A security team ran a stateful protocol fuzzing campaign against a network service using two fuzzer configurations ("A" and "B"). The raw campaign artifacts are at `/opt/campaign/`. Some data corruption occurred during collection.

Audit the campaign data and produce `/app/audit.json` with four sections:

**data_quality** — `total_records` (int), `valid_records` (int), `corrupted_records` (sorted list of test ID strings whose coverage bitmap file is malformed — determine expected bitmap size from the data), `orphan_coverage_files` (sorted list of `.bin` filenames in the coverage directory with no matching execution record).

**protocol_model** — From valid executions only: `num_states` (int), `num_transitions` (int, unique directed state pairs), `initial_state` (int, inferred from traces), `max_depth` (int, maximum shortest-path distance from the initial state to any reachable state in the transition graph).

**effectiveness** — From valid executions only: `total_unique_edges` (int, distinct coverage points across all valid tests), `config_a_median_edges` (float), `config_b_median_edges` (float), `superior_config` (string, "A" or "B" — higher median wins), `p_value` (float, two-sided Mann-Whitney U test comparing per-test coverage counts between configurations).

**regression_suite** — From valid executions only: the minimum set of tests whose combined coverage encompasses every observed edge, using greedy set-cover with ties broken by lexicographically smallest test ID. Report `test_ids` (sorted list), `suite_size` (int), `coverage_edges` (int).