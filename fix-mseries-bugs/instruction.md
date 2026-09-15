The R library at `/app/mseries.R` implements the `mseries` S3 class for time-indexed measurement data. Several functions produce incorrect results under certain conditions, and the `resample()` function is incomplete.

Fix all correctness defects and complete the `resample()` implementation so the library passes the test suite.

**Function specifications** — every analytical function must conform:

- `window_aggregate(x, window_width, FUN)` — Partitions observations into contiguous non-overlapping windows spanning the full time range. Applies `FUN` to values in each window. Every observation must be assigned to exactly one window.
- `deduplicate(x, by)` — Removes observations with duplicate keys, keeping the first occurrence. Timestamp identity must be evaluated at full machine precision.
- `nearest_merge(x, ref, max_gap)` — For each observation in `x`, finds the `ref` observation whose timestamp has the smallest absolute distance. Returns a data frame with columns `timestamp`, `x_value`, `ref_value`, `distance`. Merged value is `NA` when the minimum distance exceeds `max_gap`.
- `diff_series(x, lag, differences)` — Computes iterated lagged differences. Each output element is associated with the timestamp and label of the later of the two source observations that produced it.
- `resample(x, target_times, method = c("linear", "nearest", "locf"), max_gap = Inf)` — Returns a new mseries at `target_times` with values derived from `x`:
  - `"linear"`: piecewise linear interpolation between bracketing observations. `NA` for targets outside `x`'s time range or where either bracketing gap exceeds `max_gap`.
  - `"nearest"`: value of the closest observation by absolute timestamp distance. `NA` where that distance exceeds `max_gap`.
  - `"locf"`: value of the most recent observation at or before the target time. `NA` for targets before the first observation or where the gap exceeds `max_gap`.
  - Labels: `NA` for `"linear"`; inherited from the matched source observation for `"nearest"` and `"locf"`.

**Validation:** `Rscript -e 'source("/app/mseries.R"); cat("OK\n")'` must exit 0. All function signatures must be preserved.
