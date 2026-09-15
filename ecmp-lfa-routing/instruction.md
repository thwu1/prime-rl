A production network of six routers runs a proprietary binary link-state protocol (NLSP) over UDP. The network operations team needs a comprehensive routing resilience audit. A packet capture of NLSP heartbeat traffic, the protocol specification, and a routing policy file are provided in `/app/`.

## Environment

- `/app/network_capture.pcap` — Packet capture containing NLSP heartbeat advertisements and other network traffic
- `/app/protocol_spec.txt` — NLSP binary packet format specification
- `/app/routing_policy.json` — Audit policy: source router, critical destinations, cost thresholds
- `/app/routing_engine.py` — Skeleton routing engine class with method signatures

Tools available: `tshark`, `graphviz` (`dot`), Python 3.

## Required Artifacts

**`/app/routing_engine.py`** — Complete implementation supporting directed graphs with asymmetric costs, multipath forwarding when equal-cost paths exist, and backup next-hop computation for fast reroute. A backup next-hop must guarantee that traffic does not loop back through the failed element. The engine must distinguish between link-failure protection and node-failure protection, and must support incremental topology updates via event processing.

**`/app/discovered_topology.json`** — Network topology extracted from the packet capture by analyzing NLSP advertisements. Must filter out non-NLSP traffic and malformed packets using the magic field. Format:
```json
{"routers": ["A", ...], "links": [{"src": "A", "dst": "B", "cost": 3}, ...]}
```
Links are directional. Include all active unidirectional advertisements.

**`/app/topology.dot`** — Graphviz DOT diagram of the discovered topology with cost-labeled edges.

**`/app/topology.png`** — Rendered topology visualization produced from the DOT file.

**`/app/audit_report.json`** — Forwarding analysis from the policy's audit source router:
```json
{
    "forwarding_table": {
        "<dest>": {
            "cost": 0,
            "primary_next_hops": ["..."],
            "backup_next_hops": {
                "link_protecting": ["..."],
                "node_protecting": ["..."]
            }
        }
    },
    "coverage": {
        "link_protecting_pct": 0.0,
        "node_protecting_pct": 0.0,
        "unprotected_destinations": []
    },
    "policy_compliance": {
        "all_destinations_reachable": true,
        "critical_destinations_have_backup": true,
        "max_cost_exceeded": []
    }
}
```