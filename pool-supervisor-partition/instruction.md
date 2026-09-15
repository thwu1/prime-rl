A voice routing service at `/app/` manages outgoing HTTP connections to SFU (Selective Forwarding Unit) servers through `ConnectionPoolSupervisor` in `/app/supervisor.py`. Under production-like burst traffic the service suffers catastrophic performance collapse — connection success rates drop below 50%, and critical service-registry heartbeat connections are starved, causing cascading cluster-wide failures.

The benchmark at `/app/benchmark.py` reproduces the degradation. Run it to observe current behavior.

Relevant files:

- `/app/supervisor.py` — Connection pool supervisor (contains the performance problem)
- `/app/config.toml` — Service configuration with architecture and telemetry settings (not currently honored by the supervisor)
- `/app/telemetry.py` — `TelemetryRecorder` class for SQLite event logging (complete and working; do not modify)
- `/app/diagnose.sh` — Diagnostic report script (currently a non-functional stub)
- `/app/benchmark.py` — Benchmark tool (do not modify)

Diagnose the root cause of the performance collapse and fix the service. The fixed service must satisfy all of the following acceptance criteria:

- 500 concurrent connection requests achieve >85% success rate within the default timeout
- During a concurrent burst, 10 sequential critical-priority requests (`priority="critical"`, `timeout=2.0`) achieve >80% success rate
- Maximum deferred queue depth across any internal processing path (reported as `deferred_peak` by `get_stats()`) stays below 200
- 20 sequential normal-load requests achieve 100% success rate
- 50 concurrent requests achieve >95% success rate
- `/app/config.toml` is updated to properly configure the supervisor's architecture for production traffic patterns
- The supervisor integrates `TelemetryRecorder` from `/app/telemetry.py` using the database path from config, recording at minimum `request` and `connect` event types
- `/app/diagnose.sh` queries the telemetry database with `sqlite3` CLI and formats output via `jq`, producing a JSON object to stdout with `total_events` (integer) and `events_by_type` (array of objects each with `event_type` and `count` keys)

Preserve the public API of `ConnectionPoolSupervisor`: `start()`, `stop()`, `request_connection(destination, timeout=None, priority="normal")`, `release_connection(conn_id)`, `get_stats()`.