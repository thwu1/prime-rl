A C application at `/app/` implements a virtual device driver framework that processes binary commands through a dispatch table. It uses a custom pool memory allocator (`/app/src/pool.c`) and seven command handlers (`/app/src/handlers.c`). Each handler contains a distinct memory safety vulnerability — seven in total.

Produce the following deliverables:

**`/app/audit_report.json`** — JSON with a `"vulnerabilities"` array documenting every distinct vulnerability found (there are exactly seven). Each entry must contain: `"id"` (e.g. `"VULN-001"`), `"type"` (lowercase-hyphenated class name, e.g. `"heap-buffer-overflow"`, `"use-after-free"`, `"double-free"`, `"stack-buffer-overflow"`, `"integer-overflow"`, `"type-confusion"`, `"out-of-bounds"`), `"cwe"` (CWE identifier, e.g. `"CWE-122"`), `"command"` (the `CMD_*` constant from the dispatch table), `"function"` (vulnerable function name), `"file"` (source filename), `"root_cause"` (technical description), `"trigger"` (exploitation method), `"severity_score"` (integer 1-10), `"exploitation_class"` (one of: `"arbitrary-read"`, `"arbitrary-write"`, `"code-execution"`, `"denial-of-service"`, `"info-leak"`).

**`/app/hardened_pool/pool.c` and `/app/hardened_pool/pool.h`** — A drop-in replacement for the pool allocator exposing the same API (`pool_alloc`, `pool_free`, `pool_dump_stats`, `POOL_TAG` macro, `POOL_PAGED`/`POOL_NONPAGED` constants). The replacement must implement at minimum these three independent runtime defense layers:
- **Canary/sentinel validation**: place a trailing guard value after each allocation and verify it on free to detect buffer overflows.
- **Quarantine (delayed-free)**: hold freed blocks in a ring buffer or queue before returning them to the underlying allocator, preventing immediate reuse and detecting double-frees.
- **Memory poisoning**: overwrite freed regions with a fixed byte pattern (e.g. `0xDE`) so that use-after-free reads return garbage rather than stale data.

**`/app/patched/`** — Patched driver source preserving directory structure (`src/`, `Makefile`). Must integrate the hardened allocator as a replacement for `src/pool.c`/`src/pool.h` and individually fix every vulnerability that the allocator alone cannot address. Must compile with `make` and `make asan` and survive all vulnerability trigger inputs without crashing or producing ASAN errors.

**`/app/defense_assessment.json`** containing:
- `"severity_ranking"`: array ordered highest-to-lowest by severity score. Each entry with `"vuln_id"`, `"severity_score"` (integer 1-10), `"exploitability"` (one of `"trivial"`, `"moderate"`, `"complex"`), and `"justification"` (a substantive explanation of at least 30 characters describing why this severity and exploitability were assigned).
- `"exploit_chains"`: array of multi-vulnerability chain analyses (at least one). Each with `"chain_id"`, `"vulnerabilities"` (array of vuln IDs, at least 2 per chain), `"description"`, `"escalated_impact"`.
- `"defense_mapping"`: object keyed by vuln ID. Each value with `"mechanism"` (one of `"allocator"`, `"patch"`, `"both"`) and `"rationale"` (a substantive explanation of at least 20 characters describing why that defense mechanism applies).

The program reads binary command files: each command is an 8-byte packed header (`uint8_t command_id, uint8_t subcommand, uint16_t flags, uint32_t payload_length`) followed by `payload_length` bytes. Build with `make` or `make asan`.