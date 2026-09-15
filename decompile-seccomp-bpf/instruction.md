A compiled seccomp-BPF filter binary is at `/app/seccomp_filter.bpf`. This 480-byte file contains a 60-instruction classic BPF (cBPF) program extracted from a container process's active seccomp filter via `PTRACE_SECCOMP_GET_FILTER`. The filter operates on `struct seccomp_data` and encodes a non-trivial security policy: some syscalls are unconditionally allowed, others have argument-level conditions (value equality checks, bitmask tests), and several use distinct return actions or errno values.

Standard BPF analysis and syscall resolution tooling is installed (`seccomp-tools` for BPF disassembly, `scmp_sys_resolver` from libseccomp for architecture-aware syscall resolution, `ausyscall` from auditd). No syscall number-to-name mapping file is provided.

## Part 1: Accurate Profile Reconstruction

Reverse engineer the BPF filter and produce a Docker-format seccomp profile JSON at `/app/seccomp_profile.json` that accurately represents the filter's complete behavior. The profile must capture:

- The correct `defaultAction` with `defaultErrnoRet` if the default returns a specific errno
- The `architectures` list reflecting the filter's architecture check
- All `syscalls` entries: unconditionally allowed syscalls (by resolved name), conditionally allowed syscalls with `args` (using `SCMP_CMP_EQ` or `SCMP_CMP_MASKED_EQ` with correct `index`, `value`, `valueTwo`, and `op`), and syscalls with non-standard actions (`SCMP_ACT_LOG`, `SCMP_ACT_ERRNO` with a different errno than the default, `SCMP_ACT_KILL_PROCESS`)

Use standard Docker/OCI seccomp profile constant names (e.g. `SCMP_ACT_ALLOW`, `SCMP_ACT_ERRNO`, `SCMP_ACT_LOG`, `SCMP_ACT_KILL_PROCESS`, `SCMP_ARCH_X86_64`, `SCMP_CMP_EQ`, `SCMP_CMP_MASKED_EQ`).

## Part 2: Security Hardening

The extracted filter has security deficiencies unsuitable for production. Evaluate its posture and produce a hardened profile at `/app/hardened_profile.json` that enforces these policies while preserving all other rules unchanged:

1. **No audit-only actions**: The profile must not contain any `SCMP_ACT_LOG` rules. Any syscall the original filter handles with LOG must be escalated to `SCMP_ACT_KILL_PROCESS`.

2. **No lenient errors for privileged operations**: Any syscall assigned a non-default `SCMP_ACT_ERRNO` (i.e., with a different `errnoRet` than the profile's `defaultErrnoRet`) must be escalated to `SCMP_ACT_KILL_PROCESS` (with no `errnoRet`). Returning a specific error code allows retry attacks and leaks filter structure.

3. **Keyring isolation**: The hardened profile must explicitly block `add_key`, `request_key`, and `keyctl` with `SCMP_ACT_KILL_PROCESS` entries. These currently fall through to the default action but must be explicitly killed to prevent container keyring attacks.

4. **Extended namespace restrictions**: The `clone` conditional rule must additionally block `CLONE_NEWNS` (mask `0x00020000`, `valueTwo` `0`) alongside the existing restriction. Both `SCMP_CMP_MASKED_EQ` conditions must appear in the same rule's `args` array (AND semantics) so that clone is allowed only when neither flag is set.