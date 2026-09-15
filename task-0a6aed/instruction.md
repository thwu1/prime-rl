Build a sorted set engine and RESP protocol server at `/app/`.

## Engine

Complete `/app/sorted_set.py` — a full implementation conforming to the abstract class in `/app/interface.py`. Read that file carefully for API signatures, behavioral semantics, and structural requirements that your implementation must satisfy.

The engine must support: ZADD (with NX/XX/GT/LT/CH flags), ZREM, ZSCORE, ZCARD, ZRANK, ZREVRANK, ZRANGE, ZRANGEBYSCORE, ZCOUNT, ZPOPMIN, ZPOPMAX, and ZINCRBY — all with correct Redis 7 semantics. Elements are ordered by `(score, member)` — ascending score first, then lexicographic member for ties.

Redis 7 runs on port 6379. Use `redis-cli` to explore command behavior when the interface documentation is ambiguous.

## Server

Complete `/app/server.py` — a TCP server on port 6380 that accepts standard Redis clients. The provided stub handles TCP connections, RESP2 message parsing, and response serialization. Implement the `command_dispatch` method to translate incoming Redis wire-protocol commands into engine method calls with correct argument parsing and response formatting.

The server must also handle PING, COMMAND/COMMAND DOCS, SELECT, CONFIG, DEL, and FLUSHALL for client tool compatibility. It must support multiple independent keys (one engine instance per distinct key name).

Validate interactively with `redis-cli -p 6380` and measure throughput with `redis-benchmark -p 6380 -q -n 5000 -c 1 -t zadd`.

## Starting state

- `/app/interface.py` — abstract class (read-only reference)
- `/app/sorted_set.py` — stubs raising `NotImplementedError`
- `/app/server.py` — RESP server with TCP + parsing provided, dispatch TODO