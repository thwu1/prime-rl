A multi-tenant TCP proxy at `/app/proxy.py` routes connections from three services to distinct backend echo servers. Each outgoing connection is bound to a source port from a managed pool of 100 ports (40000-40099) before connecting to its backend. Three backends listen at 127.0.0.1:8001, 127.0.0.1:8002, and 127.0.0.1:8003 (started by `/app/backend.py`). Service configuration is in `/app/config.json`.

The proxy's `PortAllocator` treats every source port as globally exclusive — once any service binds to port 40005, no other service can use it regardless of which backend it connects to. This limits the entire system to approximately 100 total connections across all three services.

Redesign the proxy's port allocation and connection establishment strategy so that:

- Service A maintains at least 90 concurrent connections to 127.0.0.1:8001
- Service B maintains at least 90 concurrent connections to 127.0.0.1:8002
- Service C maintains at least 8 concurrent connections to 127.0.0.1:8003, using only source ports in the range 40050-40059 (audit compliance)
- Total concurrent connections exceed 190 — all using source ports from the 40000-40099 pool
- Total connection errors remain below 10

Modify files under `/app/`. Do not change `/app/backend.py`. Tests independently verify actual TCP connection state at the kernel level via `ss`, not proxy self-reporting.