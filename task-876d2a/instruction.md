The OpenROAD chip design flow generates physical design metrics (timing slack, design area, DRC violations, clock skew, etc.) validated through a tolerance-based regression system. Metric limits are derived from reference runs using tolerance expressions that depend on cross-metric variables and mathematical functions.

The metric definition file at `/app/metric_defs.json` describes 22 physical design metrics from the OpenROAD RTL-to-GDSII flow. Each definition includes a comparison operator and a limit expression. Limit expressions reference `$value` (the metric's own reference value), `$clock_period` (resolved from `DRT::clock_period` in the same metrics file), and `$instance_count` (resolved from `IFP::instance_count`). Expressions use standard arithmetic plus `min()` and `int()` functions.

The semantics originate from the OpenROAD regression framework: limits are computed FROM a reference run's metrics values using tolerance margin formulas, then a different run's metric values are checked AGAINST those computed limits. For example, the TNS (total negative slack) limit `$value - $clock_period * 0.1 * $instance_count * 0.1` allows the new run's TNS to be worse by an amount proportional to clock period and design size. Metrics like `DRT::drv` (design rule violations) use `$value` directly as the limit — a strict non-regression check.

Sample flow runs from gcd (363 instances, 485ps clock) and aes (12180 instances, 2ns clock) designs on the NanGate45 technology node are in `/app/runs/`. One degraded run with intentionally worsened metrics is included.

Implement `/app/metrics_engine.py` with these subcommands:

**`generate-limits <metrics.json> -o <output.json>`** — Evaluate each metric's limit expression using the reference metrics values and write the resulting limits as a JSON object mapping metric names to computed limit values (as strings).

**`check <metrics.json> <limits.json>`** — Compare each metric against its limit using the defined comparison operator. Print JSON to stdout: `{"overall": "pass"|"fail", "metrics": [{name, value, limit, cmp_op, status}], "errors": [...]}`. Exit 0 if all metrics pass with no errors, 1 otherwise.

**`margin-report <metrics.json> <limits.json>`** — Compute absolute margin per metric: `limit - value` for `<`/`<=` operators, `value - limit` for `>`/`>=`. Positive margin means passing. Print JSON to stdout: `{"metrics": [{name, value, limit, cmp_op, margin, status}]}`.

**`compare <metrics1.json> <metrics2.json>`** — Compute `delta = value2 - value1` and `percent_change = delta / |value1| * 100` (null when value1 is zero). Print JSON to stdout: `{"metrics": [{name, value1, value2, delta, percent_change}]}`.

Metric definitions are loaded from `/app/metric_defs.json`. All numeric values in metrics files are stored as strings.