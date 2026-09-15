Six network incidents are stored in `/app/incidents/`. Each incident `<name>` has:
- `<name>.pcap` — captured packets arriving at the server's interface
- `<name>.json` — iptables rule configuration and conntrack table capacity (`conntrack_max`)

Rules in the JSON are keyed by `table_chain` (e.g. `raw_PREROUTING`, `mangle_PREROUTING`, `filter_INPUT`). Each rule has a `match` object (all fields must match) and an `action`. Rules are evaluated sequentially; first match wins. Default policy is ACCEPT if no rule matches.

Write `/app/analyzer.py` to model the kernel's netfilter processing pipeline for each incident and produce `/app/results/<name>.json`:

```json
{
  "counters": {"raw_PREROUTING": <int>, "mangle_PREROUTING": <int>, "filter_INPUT": <int>},
  "conntrack_entries": <int>,
  "conntrack_drops": <int>,
  "verdicts": ["ACCEPT"|"DROP"|"CT_DROP", ...]
}
```

- `counters` — packets entering each chain
- `conntrack_entries` — confirmed flows remaining after processing
- `conntrack_drops` — packets silently dropped by conntrack table exhaustion
- `verdicts` — per-packet outcome in pcap order

Run: `python3 /app/analyzer.py`