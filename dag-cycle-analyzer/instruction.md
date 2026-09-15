A data platform runs 11 workflow DAGs defined in YAML at `/app/dags/`, with pool configuration at `/app/config/pools.yaml`. Historical task execution records are stored in a SQLite database at `/app/metadata.db`.

DAGs are triggered either by cron schedules or by dataset events — when a DAG produces a dataset, any DAG consuming that dataset may be triggered. Each task within a DAG claims pool slots from the DAG's assigned pool while running, and tasks execute according to their declared upstream dependencies.

The platform team has reported three categories of operational issues:

**Circular dataset triggers** — Some dataset-triggered DAGs trigger each other in loops, causing runaway scheduler behavior. Identify all distinct simple trigger loops (where no dataset repeats within the loop except at the start and end) across the DAG fleet and the DAGs involved in each.

**Theoretical pool overcommitment** — When multiple DAGs assigned to the same pool are active simultaneously, the pool may be oversubscribed. Determine the worst-case concurrent slot demand for each pool, accounting for which tasks within each DAG can physically run at the same time based on dependency constraints. Flag pools where this worst-case demand exceeds the pool's configured capacity.

**Historical pool saturation** — The metadata database contains actual task execution timestamps and slot usage. Analyze these records to find pools where actual concurrent slot usage has exceeded capacity at any point in time, and identify which DAGs were responsible at the moment of peak usage.

Implement `/app/analyzer.py` that reads all data sources and writes `/app/analysis_report.json` containing:

- **`dataset_dependency_cycles`** — Array of `{"cycle": [<dataset names forming the loop, starting dataset repeated at end>], "involved_dags": [<DAG IDs>]}`
- **`pool_bottlenecks`** — Array of `{"pool": <name>, "capacity": <int>, "max_concurrent_demand": <int>, "contributing_dags": [<dag IDs>]}` for pools where theoretical demand exceeds capacity
- **`observed_pool_saturation`** — Array of `{"pool": <name>, "capacity": <int>, "peak_concurrent_slots": <int>, "contributing_dags": [<dag IDs sorted>]}` for pools where historical peak exceeded capacity
- **`total_dags`** — Integer count of loaded DAGs
- **`total_datasets`** — Integer count of unique dataset names