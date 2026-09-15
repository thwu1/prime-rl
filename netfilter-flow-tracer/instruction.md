A production Linux firewall experienced unexplained packet drops during a traffic surge. The server's `iptables-save` ruleset dump, conntrack sysctl parameters, and a captured packet trace are at `/app/config/`. Create `/app/nftrace.py` that simulates how the kernel's netfilter subsystem processed each packet and produces a forensic JSON report.

```
python3 /app/nftrace.py <config_dir> <output_file>
```

Each config directory contains `iptables.rules` (verbatim `iptables-save` output with `*raw`, `*mangle`, `*filter` tables), `sysctl.conf` (`nf_conntrack_max` and `nf_conntrack_tcp_loose` values), and `packets.json` (ordered packet array with `id`, `protocol`, `src_ip`, `src_port`, `dst_ip`, `dst_port`, `tcp_flags`, `size_bytes`).

The simulator must correctly model the netfilter pipeline for locally-destined inbound packets: raw PREROUTING, conntrack state lookup (with table capacity enforcement), mangle PREROUTING, filter INPUT. It must handle conntrack table overflow (silent drops when full), NOTRACK bypass giving UNTRACKED state, the CT target, confirmed vs unconfirmed conntrack entries (confirmation occurs only on final ACCEPT), and `tcp_loose` semantics (when disabled, non-SYN TCP packets to unknown flows get INVALID state instead of creating NEW entries).

Output JSON structure:

```json
{
  "packet_results": [
    {
      "packet_id": 1,
      "verdict": "ACCEPT",
      "drop_layer": null,
      "conntrack_state": "NEW",
      "matched_rules": [2, 3, 7]
    }
  ],
  "rule_counters": {
    "1": {"packets": 5, "bytes": 300}
  },
  "conntrack_stats": {
    "confirmed_entries": 8,
    "overflow_drops": 5,
    "unconfirmed_drops": 1
  }
}
```

`verdict`: `"ACCEPT"` or `"DROP"`. `drop_layer`: one of `null`, `"raw_PREROUTING"`, `"conntrack_overflow"`, `"mangle_PREROUTING"`, `"filter_INPUT"`. `conntrack_state`: one of `"NEW"`, `"ESTABLISHED"`, `"UNTRACKED"`, `"INVALID"`, or `null` (dropped before state assignment). `matched_rules`: rule IDs matched in traversal order. Rules are numbered sequentially starting at 1 across all tables in `iptables-save` order. Every rule must appear in `rule_counters`, even with zero counts. Match extensions: `--dport`, `--sport`, `-s`/`-d` (IP/CIDR), `--ctstate` (comma-separated), `--tcp-flags` (mask, set). Targets: `ACCEPT`, `DROP`, `NOTRACK`, `CT`.

The environment includes `iptables`, `conntrack`, and `iproute2` tools for reference and experimentation.