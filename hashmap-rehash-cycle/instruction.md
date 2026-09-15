A production service using the hash table implementation at `/app/hashtable.c` is experiencing hard hangs under concurrent load. Multiple threads become unresponsive and the service must be forcefully killed. The issue does not manifest in single-threaded tests.

A stress test reproducing the issue is at `/app/stress_test.c` (build with `make`). Supporting field observations and a partial analysis from a previous engineer are in `/app/bug_report.txt` and `/app/scenario.txt`.

Diagnose the root cause and deliver all of the following:

- `/app/simulate.c` — single-threaded C program that deterministically reproduces the data structure corruption using the parameters from the bug report. Must output `CYCLE_BUCKET=<N>` and `CYCLE_ENTRIES=<key1>,<key2>` identifying the affected bucket and the entries involved.
- `/app/detect_cycle.c` — C program that can distinguish between a corrupted and healthy instance of the internal data structure. Must print `CYCLE_FOUND` when corruption is present and `NO_CYCLE` otherwise.
- Fix `/app/hashtable.c` (and `/app/hashtable.h` if needed) so that `./stress_test` completes successfully under concurrent load with all entries present (prints `PASS`).
- `/app/answer.txt` — exactly two lines: `CYCLE_BUCKET=<N>` and `CYCLE_ENTRIES=<key1>,<key2>`.

All targets build via `make`.