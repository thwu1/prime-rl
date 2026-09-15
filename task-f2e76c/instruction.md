A hierarchical network traffic shaper library (`libnetshaper`) at `/app/` was partially patched by a colleague who left notes in `/app/CHANGES.md`. The code compiles and some tests pass, but the fix is incomplete — it may have introduced new problems, and the build configuration may be hiding issues.

The library manages a tree of shaper nodes (`/app/shaper.h`, `/app/shaper.c`) with a test harness (`/app/test_shaper.c`). Build with `make -C /app` and run `/app/test_shaper all`.

Fix all bugs across `/app/shaper.c` and `/app/test_shaper.c` — both implementation defects and any incorrect test expectations. Add a new test case `batch_add_update_same` to the harness that verifies a batch containing both ADD and UPDATE operations for the same node index produces correct results (register it in the test dispatch table).

All tests must pass both in a normal build and when compiled with AddressSanitizer (`-fsanitize=address`). Pay attention to the build configuration and the Makefile's `sanitize` target.