Build a forensic analysis pipeline at `/app/` that reconstructs TCP port allocation behavior from `strace` and `ss` system traces. The pipeline must accurately predict whether socket operations succeed or fail, matching the Linux kernel's actual port allocation and sharing logic for `bind()` and `connect()` syscalls under varying socket options and operation orderings.

## Deliverables

`/app/strace_parser.py` -- Converts raw `strace -f -e trace=socket,bind,connect,getsockname,setsockopt,close` output into scenario.json format for the oracle. Must handle `[pid XXXX]` prefixed and non-prefixed output formats, per-PID FD namespaces (different processes may reuse the same FD numbers), unfinished/resumed syscalls (`<unfinished ...>` / `<... NAME resumed>`), and error detection from return values. `getsockname()` lines are informational and must not produce operations. Usage: `python3 /app/strace_parser.py <input.strace> <output.json> [--ephemeral-lo N] [--ephemeral-hi N] [--auto-src-ip IP]`

`/app/ss_parser.py` -- Extracts TCP connection state from `ss -tnep` output snapshots: TCP state, local/peer address:port, and PID/FD from optional process info. Handles variable-width column formatting, wildcard addresses, and absent process fields. Usage: `python3 /app/ss_parser.py <input.ss> <output.json>`

`/app/oracle.py` -- Predicts whether sequences of TCP socket operations succeed or fail, matching the Linux kernel's actual behavior. Reads `/app/scenario.json`, writes `/app/results.json`. See `/app/format.md` for the I/O specification, including the required output schema for per-step outcomes and final bind bucket state. The oracle must produce correct predictions for all operation orderings, including cases where the same set of operations yields different outcomes when reordered.

Sample captures are provided in `/app/captures/` for development and testing.