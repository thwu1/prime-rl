An external security audit of the IMGP image parser at `/app/src/parser.c` identified five vulnerabilities, catalogued in `/app/audit_report.md` with CWE classifications and affected function names only. No root-cause analysis, trigger conditions, or remediation strategies are provided.

Perform a full MAGMA ground-truth instrumentation of all five vulnerabilities. For each bug, analyze the cited function to identify the specific fault, derive a trigger condition that precisely captures the vulnerability semantics (avoid both over- and under-approximation), and implement a conditional fix. The MAGMA canary API and its instrumentation conventions are defined in `/app/magma/magma.h` — study the header to understand canary placement, fix guards, and compound-condition handling.

Create binary IMGP-format test inputs in `/app/tests/` that trigger each bug's canary. The instrumented project must compile under `make CANARIES=1` and `make CANARIES=1 FIXES=1`. Verify detection via `/app/imgparse` and `/app/monitor`.

The build system, canary runtime, and monitor tool are provided at `/app/Makefile`, `/app/magma/runtime.c`, and `/app/magma/monitor.c`.