An AI accelerator executes computational DAGs (MatMul and Pointwise operations) on hardware with a three-tier memory hierarchy: slow memory (infinite capacity, limited bandwidth), fast memory (finite capacity, zero-cost access), and ephemeral registers (zero capacity for intermediates within fused operator groups). Execution is governed by a roofline performance model where per-step latency equals `max(compute_time, memory_transfer_time)`.

The complete cost model specification is at `/app/spec.md`. A reference cost model evaluator is at `/app/evaluate.py` — use it to validate and score candidate schedules. Example benchmark problems are in `/app/benchmarks/`.

## Task

Create `/app/scheduler.py` — a Python program that reads a problem JSON and outputs an optimized execution schedule to stdout:

```
python3 /app/scheduler.py <problem.json>
```

The scheduler must analyze the DAG and produce a valid schedule (JSON matching the format in `/app/spec.md`) that minimizes total latency by jointly optimizing:

- **Operator fusion**: grouping connected ops into subgraphs to eliminate intermediate tensor transfers (making them ephemeral)
- **Tiling granularity**: choosing `[w, h, k]` per subgraph to balance compute padding vs. memory pressure, including split-K reduction for MatMul chains under tight memory
- **Tensor retention**: keeping selected output tensors in fast memory across subgraph boundaries to avoid redundant slow-memory round-trips
- **Traversal ordering**: permuting the spatial tile execution sequence to maximize MatMul input data reuse (e.g., zigzag/snake patterns that preserve LHS row-strip or RHS column-strip residency)

The output must include correct `subgraph_latencies` consistent with the cost model.

Use `/app/evaluate.py` as a validation oracle during development:
```
python3 /app/evaluate.py <problem.json> <solution.json>
```
It returns `{"valid": true, "total_latency": <float>, ...}` for valid schedules.