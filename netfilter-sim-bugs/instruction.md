A netfilter packet flow simulator at `/app/netfilter_sim.py` models incoming packet processing through the iptables chain hierarchy with connection tracking. The simulator produces incorrect results for test scenarios at `/app/scenarios/`. Run `python3 /app/run_sim.py` to see which scenarios fail and how the actual outputs differ from expected values.

Fix the simulator so all five scenarios produce correct results.

A packet capture at `/app/captures/traffic.pcap` contains 770 packets of mixed legitimate and attack traffic. The same flow metadata (without payload data) is at `/app/traffic_mix.json` with a `conntrack_max` of 150.

A strategy evaluation framework at `/app/evaluate.py` can assess filtering strategies against pcap captures given a classification of known attack patterns, but its match engine is incomplete. Fix it so all match types work. Five candidate defense strategies are provided at `/app/strategies/`.

Write a traffic classification file defining attack patterns to `/app/output/classification.json` using the format documented in `evaluate.py`. Using the fixed framework, evaluate each of the five strategies against the traffic capture with your classification. Write results to `/app/output/evaluation.json`:

```json
{
  "strategies": {
    "<strategy_name>": {
      "tp": "<int>", "fp": "<int>", "fn": "<int>", "tn": "<int>",
      "precision": "<float>", "recall": "<float>", "f1": "<float>", "fpr": "<float>"
    }
  },
  "best_strategy": "<name with highest f1>",
  "deficiency_count": "<fn of best strategy>"
}
```

Design an optimal set of netfilter rules that mitigates all identified attack vectors while preserving legitimate traffic. Write the rules to `/app/output/rules.json` as a JSON array using the rule format from scenario files (objects with `table`, `chain`, optional match fields, and `action`). Constraints:

- All attack packets must be dropped and all legitimate packets accepted
- Conntrack table entries must not exceed 120
- No conntrack table overflows (conntrack_drops must be 0)
- At least 60% of packet drops must occur in the raw PREROUTING chain