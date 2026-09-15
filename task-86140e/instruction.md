A TiDB database cluster's monitoring system has captured several slow query execution plans and stored them in `/app/data/monitoring.db` (tables: `raw_plans`, `system_config`). A separate database at `/app/data/incidents.db` contains historical performance incidents with verified root cause labels and records of past remediation attempts with measured effectiveness (tables: `historical_incidents`, `remediations`).

A metric extraction CLI is installed at `/app/tools/plan-extract` and available on `PATH`.

Produce a triage report at `/app/triage_report.json` conforming to `/app/schema.json`:

- **Classify** each incoming plan by matching its extracted metrics against patterns in the historical incident data. Plans that don't match any known anomaly pattern should be labeled `healthy`.
- **Rank remediations** for each anomalous plan by computing average historical effectiveness per strategy for that root cause class.
- **Identify correlations**: determine whether any incoming plans are related symptoms of a single underlying issue and name their shared root cause.