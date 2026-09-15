The naive UDP client at `/app/client_naive.py` demonstrates a fundamental Linux limitation: each outgoing UDP `connect()` exclusively locks a source port via `bind()`, capping total connections at the source port pool size. With ports 50000-50063 (64 ports) and 8 destination echo servers on 127.0.0.1:9001-9008, only 64 connections can be established despite 512 unique 4-tuples being theoretically available.

Create `/app/connectx.py` that overcomes this limitation by reusing source ports across different destinations while preventing UDP socket overshadowing. Requirements:

- Expose an importable function `connect_udp(src_ip, src_port, dst_ip, dst_port)` that returns a connected `socket.socket`, allowing the same source port to serve connections to different destinations
- Detect and refuse 4-tuple conflicts, including those from sockets held by other callers or processes — not just an in-process registry
- When executed as a script, create at least 400 concurrent connected UDP sockets to echo servers on 127.0.0.1:9001-9008 using only source ports 50000-50063, verifying each connection with a data round-trip
- Write `/app/results.json` with keys: `total_connections`, `unique_tuples`, `duplicates`, `port_range_size`, `round_trip_successes`, `round_trip_tested`
- Write `/app/connections.txt` with one line per connection in format `src_ip:src_port dst_ip:dst_port`

Reference echo server: `/app/echo_server.py`. Study `/app/client_naive.py` to understand the failure mode.