Build `/app/scp.py` — a Python CLI tool that orchestrates operations across a simulated database cluster. The tool must execute YAML-defined workflows against cluster nodes, support interruption and resumption of jobs, and produce diagnostic reports.

The environment at `/app/` provides:
- `spec.md` — Interface contracts and behavioral requirements
- `cluster.json` — Cluster topology (nodes across availability zones)
- `node_simulator.py` — Node operation simulator with persistent state
- `webhook_server.py` — HTTP endpoint that records webhook deliveries to a JSONL log
- `workflows/` — YAML workflow definitions

Verification tests exercise the tool as a subprocess, validating correctness through exit codes, persisted database state, execution logs, and external side effects.