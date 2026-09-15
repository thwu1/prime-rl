The PIPS L1 instruction cache prefetcher from the IPC-1 competition (ISCA 2020) is at `/app/pips_prefetcher.cc`. ChampSim simulator framework headers are in `/app/include/`. Competition rules describing the storage budget semantics are at `/app/ipc1_rules.txt`.

Build `/app/audit.sh` — a shell pipeline that uses the C preprocessor (`gcc -E`) with the provided simulator headers to resolve macro definitions, performs a complete bit-level audit of the prefetcher's hardware storage, explores alternative configurations, and writes the analysis to `/app/results.json`.

Design-space exploration: vary OFFSETBITS (12–28), LHT_LOGSETS (6–14), and LHT_NUMWAYS (1–16), keeping all other parameters at their source-code defaults. Identify the non-dominated frontier maximizing both total LHT entry count and prefetch reach distance. For each unique reach value, only the configuration achieving the highest entry count belongs on the frontier.

`/app/results.json` must contain:

- `original_config`: bit-level storage breakdown of the default configuration — fields `entry_data_bits`, `lht_entry_bits`, `scc_entry_bits`, `lht_entries`, `scc_entries`, `lht_bits`, `scc_bits`, `misc_bits`, `total_bits`, `total_kb`, `within_budget`
- `sweep`: `total_configs_evaluated`, `valid_configs`
- `pareto_front`: frontier ordered by entries descending — each with `offsetbits`, `logsets`, `numways`, `lht_entries`, `max_reach`, `total_bits`, `combined_score`
- `best_combined`: frontier configuration maximizing harmonic mean of `lht_entries` and `max_reach` — with `offsetbits`, `logsets`, `numways`, `lht_entries`, `max_reach`, `combined_score`