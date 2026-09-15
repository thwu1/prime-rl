A production web service has been degrading progressively over five monitoring windows. Folded stack profiles (`func1;func2;...;funcN count`) are at `/app/profiles/t0.folded` through `/app/profiles/t4.folded` — `t0` is the healthy baseline, `t4` the worst. System metrics are at `/app/metrics.csv`. The FlameGraph toolkit is at `/app/FlameGraph/`.

Many functions show growing sample counts across windows, but the team suspects a single underlying cause. Investigate the profiles, determine the true root cause, and write `/app/results.json` with:

- `root_cause` (string): The function that is the primary source of the regression.
- `regression_category` (string): One of `"lock_contention"`, `"cpu_compute"`, `"memory_allocation"`, `"io_blocking"`.
- `onset_window` (int, 1–4): The monitoring window where the root cause first becomes detectable.
- `inclusive_fraction_series` (5 floats, 4dp): Root cause's inclusive sample fraction at each window t0–t4.
- `self_fraction_series` (5 floats, 4dp): Root cause's exclusive (leaf-only) sample fraction at each window t0–t4.
- `cascading_functions` (sorted strings): Functions absent from t0 that appear in later windows as downstream effects of the root cause.
- `propagation_ancestors` (sorted strings): All functions that appear as callers of the root cause in any stack across all profiles, excluding `main` and the root cause.
- `subsystem_regression_share` (dict, 4dp): Each top-level subsystem's (direct children of `main`) share of the total sample count increase from t0 to t4.
- `pearson_ctx_switches` (float, 4dp): Pearson correlation between root cause inclusive fraction series and `ctx_switches_per_sec` from metrics.
- `growth_classification` (dict, keys sorted): For every function present in t1–t4 but absent from t0, classify as `"root_cause"`, `"causal_descendant"`, or `"independent"`.
- `diff_svg_path` (string): Generate a differential flame graph comparing t0 and t4 at `/app/output/diff_t0_t4.svg`.