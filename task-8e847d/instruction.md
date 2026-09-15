A Layer-4 TCP load balancer is deployed at `/app/lb.py` reading `/app/config.yaml`. It serves multiple frontends with different algorithms (weighted round-robin, least-connections, IP hash), PROXY protocol v1 injection, per-source-IP rate limiting, periodic TCP health checks, and an HTTP admin API. Start it with `python3 /app/lb.py`.

The deployment has multiple interrelated defects. Operations reports:

- **Traffic distribution anomalies**: weighted backends receive traffic in consecutive bursts rather than smooth interleaving, and the least-connections algorithm does not spread load across equally-loaded backends.
- **PROXY protocol rejections**: downstream services reject forwarded connections citing malformed PROXY protocol v1 headers — capture traffic with `tcpdump` on the backend ports to inspect the raw headers on the wire.
- **Health check instability**: backends recovering from failures are reintroduced to the pool before the configured `healthy_threshold` consecutive successes are reached. Use `ss` or `lsof` to monitor health-check connection patterns.
- **Rate limiting bypass**: the per-source-IP token-bucket rate limiter on the `rate_limited` frontend does not actually limit connection rates. Attach `strace` to the running process to observe the rate-limiting code path.
- **Backend lifecycle issues**: the drain API endpoint (`POST /backends/drain`) reports success but drained backends continue receiving new connections; connection byte counters in the stats API are partially broken.

Diagnose all defects and fix `/app/lb.py`. The corrected daemon must handle concurrent connections via asyncio, shut down cleanly on SIGTERM, and pass all operational checks.

An echo backend at `/app/backends/echo_server.py <port>` is provided — it returns JSON with `backend_port`, `proxy_header`, and `data` fields, automatically stripping PROXY v1 headers.