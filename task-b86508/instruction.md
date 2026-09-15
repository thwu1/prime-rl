A three-node Redis cluster deployment exists at `/app/`. Node configuration files are in `/app/conf/`, persistent data directories (containing saved cluster state and loaded data) are under `/app/data/`, and the canonical dataset is at `/app/dataset.csv`. Monitoring alerts captured during a prior staging run are at `/app/alerts.log`.

`redis-server` and `redis-cli` are pre-installed.

Deliver a production-ready cluster on ports 7000, 7001, and 7002 that satisfies:

- All three nodes running with `cluster_state:ok`
- Each node owns between 4500 and 6000 hash slots
- Every key-value pair from `/app/dataset.csv` is accessible via `GET` on the node that currently owns its hash slot
- A health report exists at `/app/cluster_report.json` containing:
  - `nodes`: array of objects with `port` (int), `node_id` (string), `role` (string), `slots` (string)
  - `migrated_key_count`: integer — keys relocated during remediation
  - `all_keys_verified`: boolean — true only if every dataset key was verified accessible on its correct owner