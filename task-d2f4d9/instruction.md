Three Linux SECCOMP BPF filters in `/app/` (`stdio_mmap.bpf`, `network_socket.bpf`, `fs_readonly.bpf`) are compiled binary bytecode enforcing security policies described in `/app/policies.json`. Each filter contains a subtle bug causing it to deviate from its intended policy. The BPF instruction set reference is at `/app/bpf_spec.md`.

The files use the standard Linux `sock_filter` wire format: each instruction is 8 bytes (2-byte LE code, 1-byte jt, 1-byte jf, 4-byte LE k). The filters operate on the kernel's `seccomp_data` structure — BPF loads 32-bit words, and on little-endian x86-64, the byte offset determines which half of a 64-bit argument field is accessed.

A C SECCOMP test harness (`/app/seccomp_loader.c`) and `/app/Makefile` are provided. The harness loads a binary BPF filter into the kernel's SECCOMP subsystem via `prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ...)`, forks a child that attempts a specified syscall, and reports whether the call was ALLOWED or KILLED. It also supports `--dump` mode to disassemble a binary filter file.

## Deliverables

**Decoded Filters** (`/app/decoded_filters.json`): JSON representation of all three binary filters:
```json
{"filter_name": [{"code": int, "jt": int, "jf": int, "k": int}, ...]}
```

**BPF Simulator** (`/app/bpf_sim.py`): A classic BPF virtual machine. Must export:
```python
def simulate(instructions: list[dict], seccomp_data: dict) -> int
```
- `instructions`: list of `{"code": int, "jt": int, "jf": int, "k": int}`
- `seccomp_data`: `{"nr": int, "arch": int, "instruction_pointer": int, "args": [int, int, int, int, int, int]}` (args are 64-bit unsigned)
- Returns: SECCOMP action value (e.g., `0x7fff0000` for ALLOW, `0` for KILL)

**Audit Report** (`/app/audit.json`): For each filter, the single buggy instruction and its security impact:
```json
{"filter_name": {"buggy_instruction_index": int, "description": str}}
```

**Fixed Binary Filters** (`/app/fixed/`): Corrected `.bpf` files (`stdio_mmap.bpf`, `network_socket.bpf`, `fs_readonly.bpf`) in the same binary wire format.

**Verification Log** (`/app/verify_output.txt`): Output from compiling and running the C test harness against the fixed binary filters, demonstrating correct policy enforcement via the actual kernel SECCOMP subsystem.