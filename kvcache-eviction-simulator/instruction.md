A compiled reference binary at `/app/reference` simulates a KVCache store used in disaggregated LLM serving infrastructure. It processes timestamped operation traces (JSONL) against a fixed-capacity cache and emits deterministic JSON to stdout.

Create `/app/simulator.py` — a drop-in replacement that produces byte-identical JSON output for any valid input trace and configuration.

**Usage**: `python3 /app/simulator.py --config <config.json> --trace <trace.jsonl>`

**Provided at `/app/`**:
- `reference` — compiled reference binary (source not available)
- `config.json` — sample configuration
- `traces/` — sample operation traces
- `expected/` — pre-computed reference outputs for each sample trace

The sample traces cover only a subset of the simulator's behaviors. You must craft additional probe traces and diff your implementation's output against the reference binary to discover all operation semantics, edge cases, and interactions (eviction policies, protection mechanisms, failure modes, timing boundaries). `jq` is available for JSON analysis.