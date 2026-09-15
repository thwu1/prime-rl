A Redis Sentinel-managed cluster experienced a network partition that caused a split-brain condition. During the partition, both Node A (port 6379) and Node B (port 6380) independently accepted writes as masters. Node A subsequently crashed mid-write and is currently unable to start. Node B remains running as a standalone master with its divergent dataset.

The cluster is in a degraded state: Node A is down, the Sentinel instances have conflicting views of the cluster topology with stale epoch and discovery state from the failed failover, and the Flask application (port 5000) cannot serve requests.

Recover the full cluster to operational status with a correctly reconciled dataset. The reconciliation policy is defined at `/app/reconciliation_rules.md` — follow it precisely, including all override rules and the required report schema.

After recovery:
- Node A (port 6379) is the designated master with the complete reconciled dataset
- Node B (port 6380) is a functioning replica of Node A with replication link up
- All three Sentinel instances (ports 26379, 26380, 26381) correctly monitor the master under service name `mymaster` at port 6379
- The Flask application at `http://localhost:5000/health` returns HTTP 200 with `{"status": "ok"}`
- `http://localhost:5000/records/count` reports the correct total record count
- A reconciliation report at `/app/reconciliation_report.json` documents all conflict resolutions per the schema in the rules document

Configuration files are in `/etc/redis/`. Logs are in `/var/log/redis/` and `/var/log/supervisor/`. The application source is at `/app/app.py`. Services are managed by supervisord (`/etc/supervisor/supervisord.conf`).