`/app/firmware/` contains ARM Cortex-M4 bare-metal firmware source code for a car key fob system. The firmware implements PIN authentication, encrypted unlock command processing, device pairing, and rolling-code challenge-response protocols. It is compiled with `arm-none-eabi-gcc` at `-O2` optimization. Build with `make -C /app/firmware`.

Perform a security audit of this firmware. Your analysis must be grounded in the actual compiled binary (ELF disassembly via `arm-none-eabi-objdump`), not source-code review alone. Focus on:

- Whether compiler optimization alters the security properties the developer intended
- Timing characteristics of authentication routines
- Compiler and linker security-hardening features that are missing or ineffective

Produce:

1. `/app/audit_report.json` — A JSON object whose `"findings"` array contains one entry per vulnerability. Each entry must include the affected function name, the vulnerability class, severity, and a description of the security impact.

2. `/app/firmware_fixed/` — A complete, self-contained copy of the firmware with all identified vulnerabilities remediated. Must compile cleanly via `make -C /app/firmware_fixed` and all security-critical memory wipe operations must survive `-O2` optimization in the fixed version.