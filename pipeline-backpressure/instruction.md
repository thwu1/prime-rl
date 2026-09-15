A discrete-event simulation of a 3-stage request processing pipeline is at `/app/simulation.py`. Under a workload that ramps from 200 req/s to 2000 req/s and back, the system enters a latency death spiral and never recovers — queue depths grow without bound and tail latency climbs indefinitely even after load returns to normal.

Two interrelated defects cause this:

1. **Unbounded queues** between pipeline stages allow request backlog to accumulate faster than the system can drain it. The processing stage is the bottleneck (~2.2 ms base service time, 5% probability of 8x latency spikes). Without queue capacity limits, the ingress stage feeds the processing stage faster than it can consume, and the resulting backlog takes far longer to drain than the recovery phase allows.

2. **Coordinated omission in the metrics** — latency percentiles are computed only over completed requests, hiding the thousands of requests trapped in the queue whose true latency is orders of magnitude higher.

Modify the simulation so the pipeline degrades gracefully under sustained overload and recovers promptly when load subsides. The fixed system must implement bounded queues sized using queueing theory (Little's Law), multi-stage backpressure so upstream stages stall when their downstream cannot accept work, and load shedding at the ingress to reject excess arrivals when the system is at capacity.

Run the fixed simulation to write `/app/results.json`. The output must include per-phase metrics for `normal`, `overload`, and `recovery` with both naive (`p99_ms`) and coordinated-omission-corrected (`p99_corrected_ms`) P99 latencies, plus `arrived`, `completed`, and `rejected` counts per phase. Top-level fields must include `max_queue_depths`, `in_flight_at_end`, and full request accounting where `total_arrived = total_completed + total_rejected + in_flight_at_end`.