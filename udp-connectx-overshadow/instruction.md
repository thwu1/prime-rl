Implement `/app/connectx.py` — a Python module for creating outgoing UDP connections on Linux that can **reuse source ports** across different destinations while **preventing socket overshadowing**.

## Background

On Linux, a naive `bind(src_ip, 0)` + `connect(dst)` for UDP locks one ephemeral port per connection. With ~28K ports available, this caps total concurrent outgoing UDP connections — even to different destinations. Setting `SO_REUSEADDR` allows port sharing but introduces **overshadowing**: two connected sockets can silently share the same 4-tuple `{src_ip, src_port, dst_ip, dst_port}`, where only the newest receives traffic. The older socket becomes a zombie.

Your implementation must solve both problems: enable source port reuse while detecting and rejecting duplicate 4-tuples.

## Required Functions

### `udp_connectx(src_ip, src_port, dst_ip, dst_port) -> socket.socket`

Create and return a connected `SOCK_DGRAM` (IPv4) socket. Parameters:
- `src_ip`: source IP (`str`) or `None` for automatic
- `src_port`: source port (`int`) or `0` for automatic from ephemeral range
- `dst_ip`: destination IP (`str`)
- `dst_port`: destination port (`int`)

Must support three modes:
- `udp_connectx(None, 0, dst, port)` — auto source IP and port
- `udp_connectx(ip, 0, dst, port)` — fixed source IP, auto port
- `udp_connectx(ip, port, dst, dport)` — full 4-tuple

Multiple calls with the **same source 2-tuple but different destinations** must succeed (port reuse). Calls creating a **duplicate 4-tuple** must raise `OSError` (overshadowing prevention). Created sockets must be functional for `send()`/`recv()`.

### `get_ephemeral_range() -> tuple[int, int]`

Return `(low, high)` inclusive bounds from `/proc/sys/net/ipv4/ip_local_port_range`.

### `udp_socket_lookup(family, src_addr, dst_addr) -> bytes | None`

Query the kernel to determine if a connected UDP socket exists for the given 4-tuple. Uses a kernel interface such as netlink `SOCK_DIAG` or `/proc/net/udp` — not subprocess calls to external tools.
- `family`: `socket.AF_INET`
- `src_addr`: `(ip_str, port)` tuple
- `dst_addr`: `(ip_str, port)` tuple
- Returns: an identifier (cookie, inode, etc.) if found, `None` otherwise

The lookup must return exact 4-tuple matches only. It must not false-positive on wildcard/unconnected sockets (e.g., a server socket bound to the destination port must not be reported as a conflict).