Three nftables firewall configurations at `/app/configs/` (`workstation.conf`, `server.conf`, `router.conf`) require automated security auditing. Build `/app/nft_audit.py` — a tool that statically analyzes nftables configuration files, evaluates packet behavior, and detects configuration anomalies.

## Interface

```
python3 /app/nft_audit.py <config_path> <queries_path> <output_path>
```

Run it once per configuration, writing results to `/app/results/workstation.json`, `/app/results/server.json`, and `/app/results/router.json`.

## Inputs

- `/app/configs/*.conf` — nftables rulesets defining tables, chains, named sets, and firewall rules
- `/app/queries.json` — packet specifications for verdict evaluation (test IDs, packet fields, hooks)
- `/app/schema.json` — JSON Schema defining the exact output structure and field semantics

## Requirements

Each JSON output must validate against `/app/schema.json`. The report must accurately capture:

- **Ruleset structure**: tables with address families, base chain properties including numerically-resolved priorities and default policies, named set definitions with all elements, and a directed graph of inter-chain references
- **Security posture**: TCP and UDP ports reachable on input-hook paths without source-IP restrictions (accounting for rule reachability within chains), plus boolean detection of loopback acceptance, ICMP handling, connection tracking usage, rate limiting (with per-port rate details), NAT, and masquerading
- **Packet fate**: for every test packet in the queries file, the final accept/drop verdict after traversing the applicable chain hierarchy
- **Anomalies**: non-base chains that no rule ever dispatches to, and rules rendered unreachable by a preceding unconditional terminal verdict in the same chain (see schema for exact structure)

## Environment

The `nft` package is installed. Use `man nft` or `nft -c -f <file>` for reference on configuration syntax and evaluation semantics.