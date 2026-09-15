A seccomp-BPF filter compiler at `/app/bpf_compiler.c` reads `/app/policy.txt` and emits a raw cBPF program. The compiled filter contains bugs that cause incorrect verdicts for certain inputs. Fix the compiler so the output binary filter correctly implements every rule in the policy.

Build and generate the filter:

```
make -C /app clean && make -C /app filter.bpf
```

The output `/app/filter.bpf` is a flat array of `struct sock_filter` entries (8 bytes each: `uint16_t code`, `uint8_t jt`, `uint8_t jf`, `uint32_t k`) in native little-endian byte order.

The policy file format is documented in the source header. Each line specifies either a default action or a per-syscall rule with optional argument constraints (operators: EQ, NE, GT, GE, LT, LE, MASKED_EQ). A single syscall may appear in multiple rules, and a single rule may have multiple argument constraints.

The correctly compiled filter must produce the expected seccomp action (ALLOW, KILL, KILL_PROCESS, ERRNO, TRACE, LOG) for every combination of architecture, syscall number, and argument values specified by the policy. Architecture mismatches must be rejected.

Verification loads the binary filter into a cBPF simulator and executes it against test inputs covering architecture rejection, all action types, every comparison operator, argument values that exercise the full 64-bit range, multi-rule dispatch for the same syscall, conjunctive multi-argument constraints, and masked comparison semantics.
