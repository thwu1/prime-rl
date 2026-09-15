A production nftables firewall ruleset is at `/app/firewall.nft` and a network traffic capture at `/app/traffic.pcap`. A reference classifier is at `/app/baseline_classifier.py`. `tshark` and `tcpdump` are installed for pcap analysis.

The firewall has poor classification throughput under changing traffic patterns, and the ruleset contains rules that can never be triggered.

## Required outputs

**`/app/optimized_classifier.py`** — module with an `AdaptiveClassifier` class:

- `__init__(self, ruleset_path: str)`
- `classify(self, packet: dict) -> tuple[str, int]` — `(action, rule_id)`, identical results to the baseline for every packet
- `get_rule_order(self) -> list[int]` — current evaluation order of all rule IDs
- `get_unreachable_rules(self) -> list[int]` — sorted IDs of rules that can never match any packet because an earlier rule will always intercept them
- `get_ordering_constraints(self) -> list[tuple[int, int]]` — `(i, j)` pairs where the relative evaluation order of rules i and j affects classification correctness for some possible packet
- `get_minimal_constraints(self) -> list[tuple[int, int]]` — smallest subset of ordering constraint pairs that, when all respected, ensure every other ordering constraint is also satisfied

The classifier must achieve at least 5x throughput over the baseline while maintaining classification correctness. Its internal evaluation order must change during classification to reflect observed traffic patterns without breaking correctness.

**`/app/ruleset_analysis.json`**:

- `total_rules` (int)
- `unreachable_rule_ids` (sorted list of ints)
- `ordering_constraint_count` (int)
- `minimal_constraint_count` (int)
- `phase_boundaries` (list of 2 ints — packet indices where traffic distribution shifts, ±500 tolerance)
- `per_rule_hit_counts` (dict: rule_id string → hit count, at least top 30 rules)

## Success criteria

- Classification identical to baseline for every packet in the capture
- >= 5x amortized throughput over baseline
- Evaluation order changes during classification without violating correctness
- Phase boundary detection within ±500 tolerance

Packet dict keys: `src_ip`, `dst_ip`, `src_port`, `dst_port`, `protocol`.