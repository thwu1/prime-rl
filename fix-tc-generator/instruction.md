The `/app/` directory contains a datacenter network traffic shaping environment:

- `/app/tc_generator.py` — Python script that reads `/app/bandwidth_spec.yaml` and generates `tc` HTB commands. Contains bugs producing incorrect tc command output.
- `/app/bandwidth_spec.yaml` — Single-interface HTB bandwidth specification consumed by tc_generator.py
- `/app/topology.yaml` — Two-interface HTB qdisc hierarchy (eth0: 10Gbps north-south, eth1: 25Gbps east-west/storage/RDMA) with DSCP-based traffic classification and embedded HTB invariant violations
- `/app/traffic_demands.yaml` — Per-class offered traffic loads in mbit
- `/app/sla_requirements.yaml` — Per-class minimum throughput ratio targets

Produce the following:

**1.** Debug and fix all bugs in `/app/tc_generator.py` so that `python3 /app/tc_generator.py` produces correct `/app/tc_commands.sh` and `/app/tc_report.json`. Consult `tc` man pages (`tc-htb(8)`, `tc-u32(8)`) and `ip` documentation to verify the generated commands are semantically correct.

**2.** Create `/app/tc_analyzer.py` that, when run via `python3 /app/tc_analyzer.py`, produces:

**`/app/analysis_report.json`** — JSON object with keys:
- `violations`: array of all detected HTB invariant violations, each with `type` (one of `rate_exceeds_ceil`, `ceil_exceeds_parent_ceil`, `overcommitted`, `invalid_default`), `interface`, `class_name`, `details`
- `optimized_config`: per-interface dict with `classes` (list of objects with `classid`/`name`/`rate`/`ceil`/`prio`/`is_leaf`) and `default_minor`, where all HTB invariants are satisfied
- `bandwidth_simulation`: per-interface, per-class-name dict with `allocated_mbit` (integer), `demand_mbit`, `utilization`, modeling HTB steady-state hierarchical bandwidth scheduling under the given traffic demands
- `sla_compliance`: object with `violations` array (each: `class_name`/`interface`/`required_ratio`/`actual_ratio`), `compliant_count`, `total_count`

**`/app/optimized_tc_commands.sh`** — Executable shell script containing corrected `tc` commands for both interfaces with DSCP-based u32 filter classification, correct TOS byte encoding, and proper command dependency ordering

**3.** Create `/app/nft_classify.nft` — An nftables ruleset providing equivalent DSCP-based packet classification into tc classes for both interfaces. Must use the `netdev` table family with per-interface classification chains that set `meta priority` to the appropriate tc classid.

**`/app/validation_summary.txt`** — Human-readable summary of the analysis