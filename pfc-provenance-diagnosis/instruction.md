A PFC-enabled RDMA datacenter fabric (k=4 fat-tree topology) has experienced performance anomalies visible as degraded flow RTTs. Switch telemetry, physical topology, and affected RDMA flows are provided.

## Input

- `/app/fabric.db` — SQLite database containing:
  - `switch_meta` — switch tier and pod assignment
  - `pfc_config` — PFC priority configuration: XOFF/XON thresholds, buffer sizes, causal correlation window
  - `pfc_events` — timestamped PFC pause events per switch/port/queue with queue depth
  - `port_counters` — periodic per-port byte and PFC frame counter snapshots

- `/app/topology.dot` — Graphviz DOT file describing the fat-tree physical topology; edges carry `src_port`/`dst_port` attributes encoding port-level wiring between switches

- `/app/victim_flows.json` — RDMA flows with source, destination, routing path (ordered list of network elements), and observed vs expected RTTs

## Task

Analyze PFC telemetry and network topology to identify distinct anomaly clusters in the fabric, classify each anomaly, determine which victim flows are affected, and quantify severity.

## Output

Write `/app/results.json`:

```json
{
  "anomaly_count": <int>,
  "anomalies": [
    {
      "id": <int>,
      "type": "attack" | "deadlock",
      "root_cause": {"switch": "<id>", "port": <int>, "queue": <int>},
      "propagation_depth": <int>,
      "cycle_switches": ["<id>", ...],
      "cycle_length": <int>,
      "affected_switches": ["<id>", ...],
      "affected_flow_ids": [<int>, ...],
      "severity_score": <float>
    }
  ]
}
```

For `attack`-type anomalies, include `root_cause` (originating switch/port/queue) and `propagation_depth` (maximum PFC propagation depth from root cause). For `deadlock`-type anomalies, include `cycle_switches` (ordered switches forming the cycle) and `cycle_length`. Both types require `affected_switches` (sorted), `affected_flow_ids` (victim flows whose paths traverse any affected switch), and `severity_score` (total PFC pause duration among the anomaly's contributing events divided by the cluster's time span).

Write `/app/provenance.dot` — a Graphviz directed graph (`digraph`) of PFC interactions among switches identified during analysis. Must compile with `dot -Tsvg`.