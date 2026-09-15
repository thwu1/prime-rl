A SQLMesh project at `/app/` implements an e-commerce analytics pipeline using DuckDB. It transforms raw order and product seed data through staging and intermediate layers into analytics tables (daily revenue aggregates and product performance rankings).

The project contains multiple interrelated bugs spanning configuration, model definitions, data quality audits, and unit tests. Both `sqlmesh test` and `sqlmesh plan --auto-apply --no-prompts` currently fail. After all bugs are fixed, both commands must succeed, and the resulting analytics tables (`analytics.daily_revenue`, `analytics.top_products`) must contain correct, non-empty data.

Project layout:
- `/app/config.yaml` — project and gateway configuration
- `/app/models/` — SQL model definitions (seeds, staging, intermediate, analytics)
- `/app/audits/` — custom data quality audit definitions
- `/app/tests/` — SQLMesh unit test fixtures (YAML)
- `/app/seeds/` — CSV source data