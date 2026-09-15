`/app/workdir/` contains results from a Magma ground-truth fuzzing benchmark evaluation. The directory tree under `ar/` organizes campaigns by fuzzer name, target library, program binary, and repetition ID. Each campaign directory contains a `monitor.csv` recording per-bug reach and trigger counters at regular polling intervals.

Read `/app/workdir/captainrc` for campaign parameters including the polling interval (`POLL`) and campaign timeout (`TIMEOUT`, which may use a one-letter duration suffix: `s` for seconds, `m` for minutes, `h` for hours). The monitor CSV header encodes bug identifiers with `_R` (reached counter) and `_T` (triggered counter) suffixes. A bug is first reached or triggered at the timestamp of the first data row where its counter becomes positive, computed as `(1_based_row_number) * POLL` seconds from campaign start.

Produce three output files:

**`/app/results.json`** — Nested JSON in the Magma `exp2json` format:
```
{fuzzer: {target: {program: {run_id_string: {reached: {BUG_ID: seconds_int}, triggered: {BUG_ID: seconds_int}}}}}}
```
Only include bugs actually reached or triggered in each run. Campaigns with empty or unreadable monitor data must be excluded entirely.

**`/app/statistics.json`** — Pairwise fuzzer comparisons and coverage summary:
```
{
  "pairwise": {
    "fuzzerA_vs_fuzzerB": {
      "target/program": {
        "BUG_ID": {
          "a12": <Vargha-Delaney A12 effect size>,
          "a12_magnitude": "<negligible|small|medium|large>",
          "p_value": <Mann-Whitney U two-sided p-value>
        }
      }
    }
  },
  "coverage": {
    "fuzzer": {
      "unique_reached": ["BUG_ID", ...],
      "unique_triggered": ["BUG_ID", ...]
    }
  }
}
```

Compute `A12(X, Y) = P(X > Y) + 0.5 * P(X == Y)` on time-to-trigger samples between fuzzer pairs, where X is the first fuzzer's trigger times and Y is the second's. Substitute the campaign timeout for bugs never triggered in a given run. Pairwise keys must use alphabetical fuzzer ordering (e.g., `afl_vs_aflplusplus`). Classify A12 magnitude using Vargha-Delaney thresholds: `negligible` when 0.44 <= A12 <= 0.56, `small` when 0.56 < A12 <= 0.64 or 0.36 <= A12 < 0.44, `medium` when 0.64 < A12 <= 0.71 or 0.29 <= A12 < 0.36, `large` otherwise. Coverage lists all bugs ever reached or triggered by each fuzzer across all targets and runs, sorted alphabetically.

**`/app/report.txt`** — Human-readable summary including: total campaigns analyzed, per-fuzzer bug coverage counts, best fuzzer per bug by median time-to-trigger, and any data quality issues encountered during processing.