An LLM inference serving simulator at `/opt/llm-sim/` models a disaggregated-memory architecture with paged KV cache (16-token pages, 256-page GPU capacity). KV cache pages transfer between GPU and remote memory at a bandwidth calibrated from network measurements — the simulator requires `/opt/llm-sim/calibration.json` before it will run (see `/opt/llm-sim/config.py` for the calibration formula and expected format).

## Calibration

Before the simulator can run, you must create `/opt/llm-sim/calibration.json` containing:

- `measured_bandwidth_gbps` (float): raw TCP bandwidth in Gbps measured via iperf3. Must be > 1.0.
- `remote_memory_bandwidth_mb_s` (float): derived RDMA fabric bandwidth computed as `measured_gbps * 1000 / 50`, clamped to [500, 3000]. Must fall in range (100, 10000).

## Workload

The workload (`/opt/llm-sim/workload.py`) generates 500 requests with three SLO tiers (latency-critical, interactive, batch) and a heavy-tailed size distribution (70% short / 20% medium / 10% long). The FCFS baseline (`/opt/llm-sim/scheduler/fcfs.py`) processes requests without preemption, causing severe head-of-line blocking under this workload.

A JSONL trace logger writes scheduling events when running `python3 run.py baseline`, and a SQLite schema (`/opt/llm-sim/trace_schema.sql`) is provided for structured trace analysis.

## Scheduler Implementation

Implement `/opt/llm-sim/scheduler/paged_mlfq.py` containing a `PagedMLFQScheduler` class that is a subclass of `Scheduler` from `/opt/llm-sim/scheduler/base.py`. The paged memory manager is accessible via `self._memory` (set by the simulator) for page-count and swap-cost queries. The scheduler must be preemptive — preemption must actually occur during the simulation.

## Performance Targets

Comparison is done via `cd /opt/llm-sim && python3 run.py compare`, running both FCFS and your scheduler on the same seeded 500-request workload. All of the following must hold:

- **All 500 requests complete** without starvation, with valid completion times (each request's completion time must be ≥ its arrival time and > 0, with no duplicate completions).
- **Average JCT ≤ 50% of FCFS** across all requests.
- **Short-request (≤ 100 input tokens) average JCT ≤ 25% of FCFS**.
- **SLO compliance ≥ 60%** overall (proportion of requests completing within their tier's deadline).
- **Short requests (≤ 100 input tokens) must have lower average JCT than long requests (≥ 1000 input tokens)**, demonstrating effective size-aware prioritization.