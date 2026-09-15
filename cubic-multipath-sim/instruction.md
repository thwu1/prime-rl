Implement a discrete-event congestion control simulator at `/app/simulator.py` that models QUIC multipath connections using RFC 9438 CUBIC. The simulator processes scenario files describing network paths and timed congestion events, and produces per-path congestion window evolution and throughput statistics.

## Congestion Control

Implement CUBIC (RFC 9438) with these extensions:

**Slow start**: cwnd doubles each RTT (exponential growth). Exits when cwnd >= ssthresh or on a congestion event.

**CUBIC function** (congestion avoidance, after a congestion event at time `t_epoch`):
- `K = cbrt(W_max * (1 - beta) / C)` (seconds; W_max in MSS units)
- `W_cubic(t) = C * (t - K)^3 + W_max` (MSS; t = seconds elapsed since `t_epoch`)
- `W_est(t) = W_max * beta + 3*(1-beta)/(1+beta) * t / RTT` (MSS; TCP-friendly estimate; t and RTT in seconds)
- `cwnd = max(W_cubic, W_est) * MSS` (bytes)

**Loss event**: save state for potential spurious recovery. Apply fast convergence: if `cwnd_mss < last_W_max`, set `W_max = cwnd_mss * (1+beta)/2`; else `W_max = cwnd_mss`. Then `cwnd *= cubic_beta`, `ssthresh = cwnd`, compute new K. Floor cwnd at 1 MSS.

**ECN alternative backoff**: same as loss but use `ecn_beta` instead of `cubic_beta` for the reduction and K computation. No fast convergence for ECN.

**Spurious recovery**: restore all congestion state (cwnd, ssthresh, W_max, K, t_epoch, slow start flag) to the values saved before the most recent loss/ECN event.

**Multipath**: each path has an independent congestion controller. A scheduler runs every `min(all path RTTs)` ms, selecting the path with the lowest `rtt_ms / cwnd_mss` ratio.

**Bytes delivered**: approximate per-path throughput as `avg_cwnd * elapsed_ms / rtt_ms` between state changes.

## Interface

**CLI**: `python3 /app/simulator.py --scenario <path.json> --output <path.json>`

**Import**: must export a callable `run_simulation(scenario: dict) -> dict`

## Scenario format (input)

```json
{
  "params": {
    "mss_bytes": 1200,
    "cubic_C": 0.4,
    "cubic_beta": 0.7,
    "ecn_beta": 0.85,
    "initial_cwnd_mss": 10
  },
  "paths": [{"id": 0, "rtt_ms": 50}, {"id": 1, "rtt_ms": 100}],
  "events": [
    {"time_ms": 100, "type": "loss", "path_id": 0},
    {"time_ms": 500, "type": "ecn", "path_id": 1},
    {"time_ms": 510, "type": "spurious_recovery", "path_id": 1}
  ],
  "duration_ms": 10000
}
```

Event types: `loss`, `ecn`, `spurious_recovery`. Events are processed in time order.

## Output format

```json
{
  "paths": {
    "0": {
      "final_cwnd_bytes": 12345.67,
      "loss_events": 2,
      "ecn_events": 1,
      "spurious_recoveries": 0,
      "bytes_delivered": 567890.12,
      "cwnd_at_events": [
        {"time_ms": 100, "cwnd_after_bytes": 8400.0, "event_type": "loss"}
      ]
    }
  },
  "total_bytes_delivered": 567890.12,
  "multipath_schedule": {"0": 150, "1": 50}
}
```

Counters are independent: a loss followed by spurious_recovery increments both `loss_events` and `spurious_recoveries` by 1. `multipath_schedule` records how many scheduling decisions favored each path.