A production microservices system's telemetry is available in two formats:

- **JSONL**: `/app/data/spans.jsonl` — one JSON span per line, arrival order shuffled
- **SQLite**: `/app/data/telemetry.db` — table `spans` with columns: `trace_id`, `span_id`, `parent_span_id`, `service_name`, `operation_name`, `start_time_unix_nano`, `duration_ms`, `http_status_code`, `http_method`, `http_route`, `error`, `user_id`, `region`, `build_id`, `hostname`, `is_root`

Sampling rules are defined in `/app/config/rules.yaml` and SLO definitions in `/app/config/slos.yaml`. Read and interpret these configuration files to understand what the pipeline must do.

Build a tail-based sampling pipeline that:

1. Assembles complete traces from the unordered span data. Note that root spans use three different `parent_span_id` encodings across the dataset — your pipeline must handle all of them.
2. Applies every rule from `rules.yaml` in priority order, keeping all traces that match any keep-rule and dynamically sampling the rest under the configured throughput budget.
3. Produces the output files described below.

## Required outputs in `/app/output/`

**`sampled_spans.jsonl`** — Retained spans. Each span must include an integer `meta_sample_rate` (≥1) and a string `meta_rule` (the name of the rule that caused it to be kept). All spans from a kept trace must be present with a consistent `meta_sample_rate` across the trace. Traces kept by deterministic rules must have `meta_sample_rate` of 1.

**`sampling_report.json`** — Object with keys: `total_traces` (int, count of all traces in raw data), `kept_traces` (int, count of traces in output), `rules_breakdown` (object mapping rule name to trace count), `effective_rates` (object mapping sampling key to rate details).

**`slo_report.json`** — Object with key `slos` (array). Each entry: `name`, `raw_sli` (computed from the full unsampled dataset), `sampled_sli` (estimated from the sampled data, weighted by `meta_sample_rate` to correct for sampling bias), `target`. The weighted availability SLI must approximate the true SLI within 5% relative error.

**`topology.json`** — Object with: `services` (array of all distinct service names in the data), `edges` (array of `{"caller", "callee", "call_count"}` objects representing service-to-service dependencies derived from the span data), `expected_topologies` (object mapping each `http_route` to the list of services that are typically involved in handling that route).

**`analysis.sql`** — SQL file containing the analytical queries used for threshold computation and topology extraction, directly executable via `sqlite3 /app/data/telemetry.db < /app/output/analysis.sql`. Must produce non-empty output when executed.