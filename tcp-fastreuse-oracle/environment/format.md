# TCP Port Allocation Forensic Pipeline -- I/O Specifications


## Oracle: scenario.json -> results.json

### Input: /app/scenario.json

```json
{
  "config": {
    "ephemeral_range": [60000, 60000],
    "auto_src_ip": "127.0.0.1"
  },
  "operations": [
    {"step": 1, "action": "socket", "id": "s1"},
    {"step": 2, "action": "setsockopt", "id": "s1", "option": "SO_REUSEADDR", "value": 1},
    {"step": 3, "action": "bind", "id": "s1", "ip": "127.1.1.1", "port": 0},
    {"step": 4, "action": "connect", "id": "s1", "dst_ip": "127.9.9.9", "dst_port": 1234},
    {"step": 5, "action": "close", "id": "s1"}
  ]
}
```

### Config Fields

- `ephemeral_range`: `[lo, hi]` inclusive range of ephemeral port numbers available for auto-assignment.
- `auto_src_ip`: the source IP the kernel selects when a socket has no explicit bind (simulates the routing decision for loopback destinations).

### Operation Types

- `socket`: Create a new TCP socket. Fields: `id` (string identifier).
- `setsockopt`: Set a socket option. Fields: `id`, `option` (`"SO_REUSEADDR"` or `"IP_BIND_ADDRESS_NO_PORT"`), `value` (0 or 1).
- `bind`: Bind socket to local address. Fields: `id`, `ip` (local IP string), `port` (0 for ephemeral auto-assignment, or a specific port number).
- `connect`: Connect socket to remote address. Fields: `id`, `dst_ip`, `dst_port`.
- `close`: Close socket and release its bind bucket slot. Fields: `id`.

### Notes

- `port: 0` in a `bind` operation means the kernel should auto-select from the ephemeral range.
- When `IP_BIND_ADDRESS_NO_PORT` is set, `bind(ip, 0)` records the IP but defers port allocation to the subsequent `connect()`.
- Operations are executed sequentially in step order.
- Each `id` uniquely identifies a socket across all operations.

### Output: /app/results.json

```json
{
  "steps": [
    {"step": 1, "outcome": "success"},
    {"step": 2, "outcome": "success"},
    {"step": 3, "outcome": "success", "port": 60000},
    {"step": 4, "outcome": "success"},
    {"step": 5, "outcome": "success"}
  ],
  "final_buckets": {
    "60000": {"fastreuse": 1, "num_owners": 0}
  }
}
```

### Step Result Fields

- `step`: step number matching the input operation.
- `outcome`: `"success"` or `"error"`.
- `errno`: present only when `outcome` is `"error"`. Values: `"EADDRINUSE"` (bind conflict) or `"EADDRNOTAVAIL"` (connect port exhaustion).
- `port`: present when a port is newly allocated in this step. Included for successful `bind` operations that resolve a port (not deferred by `IP_BIND_ADDRESS_NO_PORT`), and for successful `connect` operations that allocate a port (socket had no previously bound port).

### Final Buckets

State of all bind buckets after all operations have been executed.

- Keys: port numbers as strings.
- `fastreuse`: the bucket's current fastreuse state (`-1`, `0`, or `+1`).
- `num_owners`: count of sockets currently occupying this bucket.
- Buckets with zero owners (fully closed) should be omitted.

### Error Semantics

- `EADDRINUSE`: returned by `bind()` when the requested port has a conflicting owner.
- `EADDRNOTAVAIL`: returned by `connect()` when no usable ephemeral port is available within the configured range.

---

## Strace Parser: strace log -> scenario.json

### Usage

```
python3 /app/strace_parser.py <input.strace> <output.json> [--ephemeral-lo N] [--ephemeral-hi N] [--auto-src-ip IP]
```

Defaults: `--ephemeral-lo 60000 --ephemeral-hi 60000 --auto-src-ip 127.0.0.1`

### Input Format

Raw output from `strace -f -e trace=socket,bind,connect,getsockname,setsockopt,close`.

Lines may be prefixed with `[pid  XXXX]` when captured with `strace -f` (multi-process tracing). Without `-f`, lines have no PID prefix.

Relevant syscall line formats:

```
socket(AF_INET, SOCK_STREAM|SOCK_CLOEXEC, IPPROTO_TCP) = 3
setsockopt(3, SOL_SOCKET, SO_REUSEADDR, [1], 4) = 0
setsockopt(3, SOL_IP, IP_BIND_ADDRESS_NO_PORT, [1], 4) = 0
bind(3, {sa_family=AF_INET, sin_port=htons(0), sin_addr=inet_addr("127.0.0.1")}, 16) = 0
getsockname(3, {sa_family=AF_INET, sin_port=htons(60000), sin_addr=inet_addr("127.0.0.1")}, [16]) = 0
connect(3, {sa_family=AF_INET, sin_port=htons(1234), sin_addr=inet_addr("10.0.0.1")}, 16) = 0
connect(4, {sa_family=AF_INET, sin_port=htons(1234), sin_addr=inet_addr("10.0.0.1")}, 16) = -1 EADDRNOTAVAIL (Cannot assign requested address)
close(3)                                = 0
```

Unfinished/resumed syscall format (occurs when a blocking call is interleaved with another process):

```
[pid  1001] connect(3, {sa_family=AF_INET, sin_port=htons(1234), sin_addr=inet_addr("10.0.0.1")}, 16 <unfinished ...>
[pid  1001] <... connect resumed>)      = 0
```

Non-syscall lines (signals, exit notifications) must be ignored:

```
--- SIGCHLD {si_signo=SIGCHLD, si_code=CLD_EXITED} ---
+++ exited with 0 +++
```

### Output Format

Same as oracle input (scenario.json). The parser:

- Assigns unique socket IDs (`"s1"`, `"s2"`, ...) based on `socket()` call order.
- Tracks FD-to-socket mappings per PID (different PIDs may reuse the same FD number).
- Generates sequential step numbers for each operation.
- Emits operations for both successful and failed syscalls (the oracle determines outcomes independently).
- Does NOT emit operations for `getsockname()` lines (informational only).
- For unfinished/resumed calls, emits the operation at the point of completion (resumed line).

---

## SS Parser: ss output -> connections.json

### Usage

```
python3 /app/ss_parser.py <input.ss> <output.json>
```

### Input Format

Output from `ss -tnep`. Header line followed by connection lines:

```
State    Recv-Q  Send-Q    Local Address:Port     Peer Address:Port  Process
ESTAB    0       0         127.0.0.1:60000        127.9.9.9:1234     users:(("exerciser",pid=1234,fd=3))
TIME-WAIT 0      0         127.0.0.1:60001        127.9.9.9:1234
LISTEN   0       128       0.0.0.0:8080           0.0.0.0:*
```

Notes:
- Column widths are variable (whitespace-separated).
- Process info (`users:((...))`) is optional; may be absent for TIME-WAIT or unprivileged captures.
- Peer port may be `*` for LISTEN sockets.

### Output Format

```json
[
  {
    "state": "ESTAB",
    "local_ip": "127.0.0.1",
    "local_port": 60000,
    "peer_ip": "127.9.9.9",
    "peer_port": 1234,
    "pid": 1234,
    "fd": 3
  }
]
```

- `pid` and `fd` are present only when process info is available in the input.
- `peer_port` is `0` when the input shows `*`.
