A cache simulation system at `/app/` evaluates an adaptive eviction policy against random and FIFO baselines across diverse workload patterns (Zipfian, temporal locality, sequential scans, uniform). The adaptive policy combines recency and frequency signals to select eviction candidates, but benchmark results show it underperforming — on some workloads it loses to random eviction. Additionally, benchmark output varies between runs, making changes impossible to evaluate reliably.

Source files:
- `/app/engine.py` — cache engine with clock-based recency tracking and eviction pool
- `/app/policies.py` — eviction policy implementations (random, FIFO, adaptive)
- `/app/workloads.py` — workload trace generators
- `/app/benchmark.py` — evaluates all policy/workload combinations

Diagnose and fix all correctness issues. The adaptive policy must reliably outperform baselines on workloads with exploitable access patterns, and benchmark results must be fully reproducible across runs.

Run `python3 /app/benchmark.py` to produce `/app/results.json`.