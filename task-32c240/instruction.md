A connection manager at `/app/connmgr.py` handles outgoing TCP and UDP connections for a multi-service proxy. Each service binds to a specific source IP address for traffic separation. The manager uses `SO_REUSEADDR` to enable UDP source port sharing across different destinations.

Under load testing, some UDP connections silently stop receiving responses. `create_udp_connection()` returns successfully and the socket can send data, but incoming responses are never delivered to it. No error is raised. The issue only affects UDP, never TCP.

A simple reproducer: create two UDP connections with the same source IP and source port going to the same destination. Both calls succeed without error, but the first connection stops receiving any data.

Fix `create_udp_connection()` so that:

- Connection attempts that would silently break an existing connection raise `ConnectionConflictError` (already defined in the module) instead of succeeding
- The protection must cover UDP sockets created outside this `ConnectionManager` instance (e.g., by other processes or libraries)
- When `src_port=0` (auto-assigned), the manager should transparently find a safe port rather than raising an error
- Legitimate source port sharing across different destinations must continue working
- TCP functionality must not be affected
- After a socket is closed via `close_connection()`, its address should become available for reuse