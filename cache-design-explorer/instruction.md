A C cache simulator at `/app/` compiles cleanly (`gcc -Wall -Wextra`, zero warnings) but its output diverges from the specification at `/app/spec.md`, which includes a detailed reference trace walkthrough with expected output.

Source: `/app/cache.c`, `/app/cache.h`, `/app/cachesim.c`, `/app/Makefile`. Traces: `/app/traces/`. Debugging tools are available on the system.

Deliver a corrected `/app/cachesim` binary and `/app/answers.json` containing correct results for the five analysis questions defined in the spec, computed by running the fixed binary.