A MySQL production environment uses orchestrator for replication topology management, Consul for service discovery, and HAProxy for traffic routing. Five production incidents have been captured as topology JSON exports. Your job is to build a recovery analysis engine and an end-to-end pipeline that can correctly process each incident.

## Environment

- `/app/topologies/` — Five orchestrator topology JSON exports, each representing a distinct production incident
- `/app/docs/` — Reference documentation covering the full failure detection taxonomy, topology recovery mechanics, raft consensus protocol, and the Consul/GLB outage timing model. These documents are the authoritative specification for how the system should behave.
- `/app/scenarios/` — Worked example scenarios with known expected outcomes, useful for validating your implementation during development
- `/app/models.py` — Data model definitions (dataclasses and enums) for the analysis engine
- `/app/engine.py` — Abstract engine interface defining the required method signatures
- `/app/templates/haproxy_backend.cfg.tmpl` — HAProxy backend configuration template with placeholder variables
- `consul` binary at `/usr/local/bin/consul` (start in dev mode: `consul agent -dev -bind=127.0.0.1`)
- `haproxy` installed for configuration validation (`haproxy -c -f`)
- `jq` installed for JSON processing

## Deliverables

**`/app/analyze.py`** — Accepts a topology JSON file path as its first argument. Outputs a JSON recovery report to stdout containing: `cluster_name`, `failures` (list of `{type, instance, actionable}`), `recovery_attempted`, `recovery_target_is_master`, `promoted_server` (hostname:port or null), `raft_leader` (hostname or null), `estimated_outage_seconds`, and `recovery_blocked_reason` (string or null). The analysis must faithfully implement the behavior specified in `/app/docs/`.

**`/app/pipeline.sh`** — Accepts a topology JSON path and an output directory as arguments. Must use `jq`, `consul`, and `haproxy` as part of its operation. Produces `{output_dir}/report.json` containing the analysis results. When the analysis indicates a master-level recovery, Consul KV at `mysql/{cluster_name}/primary` must be updated with a JSON value `{"hostname": "...", "port": ...}` for the promoted server. When recovery is attempted, a valid HAProxy backend configuration (passing `haproxy -c -f` validation) must be generated at `{output_dir}/haproxy.cfg`.