A TCP connection simulator at `/app/tcp_sim/` is failing under integration testing. The state machine implementation in `/app/tcp_sim/connection.py` exhibits multiple protocol-level defects:

- Bulk data transfers fail when a segment's payload partially spans the receive window boundary — the segment is silently discarded instead of being delivered
- The smoothed RTT estimator reacts erratically to latency variation, causing retransmission timers to be grossly miscalibrated after even a single unusual sample
- Simultaneous close (both endpoints send FIN concurrently) causes the connection to hang indefinitely instead of progressing through the closing sequence
- Active close initiated via `Connection.close()` never completes — the connection remains stuck in its initial closing state because the peer's acknowledgment of the FIN is never matched against the recorded FIN sequence number
- After the three-way handshake, the first data acknowledgment exhibits incorrect sequence accounting, as if the handshake's own sequence state update was never committed

Diagnose and fix all bugs in `/app/tcp_sim/connection.py`.

The simulator also requires a congestion control module at `/app/tcp_sim/congestion.py`. It must export a `CongestionController` class inheriting from `CongestionControllerBase` (see `/app/tcp_sim/cc_interface.py`). Per-scenario performance targets are stored in `/app/metrics/baseline.db` — query it with `sqlite3` to determine what your implementation must achieve. The evaluation harness at `/app/harness.py` drives scenario files from `/app/scenarios/` against your implementation.

Packet captures for three network environments are at `/app/captures/*.pcap`. Analyze them and write results to `/app/analysis.json` with keys `scenario_a`, `scenario_b`, `scenario_c`, each containing `avg_rtt_ms` (float), `retransmission_pct` (float), and `packet_count` (integer). Create `/app/metrics/analysis.db` with a `network_metrics` table (columns: `scenario TEXT`, `avg_rtt_ms REAL`, `retransmission_pct REAL`, `packet_count INTEGER`, `bdp_bytes INTEGER`) populated with one row per scenario.