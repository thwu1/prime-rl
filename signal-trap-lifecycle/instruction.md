`/app/traplib.sh` is a Bash library for signal-safe process lifecycle management. It contains multiple interacting bugs across all functions. Fix all bugs so that `bash /tests/test.sh` passes.

The library must implement these contracts:

**`traplib_init`** — Register signal handlers for EXIT, TERM, INT, and HUP. Initialize internal state. Must be safely callable multiple times without losing tracked resources or causing duplicate cleanup.

**`traplib_push_handler CMD`** — Register `CMD` as a cleanup handler. Most recently registered handler executes first (LIFO).

**`traplib_mktemp_dir`** — Create a temporary directory (path printed to stdout), removed during cleanup. Must work correctly when called inside `$()` command substitution.

**`_traplib_run_cleanup [SIGNAL]`** — Internal cleanup entry point:
- `_TRAPLIB_SAVED_STATUS` must capture the `$?` active when cleanup was triggered.
- Handlers and resource cleanup execute exactly once regardless of exit path.
- Tracked process groups and processes terminated before temp directories removed.
- On signal exit (TERM/INT/HUP): the parent process must observe signal-caused termination (WIFSIGNALED), not a normal exit code.
- Must complete all registered handlers even when the calling script uses `set -e` and a handler returns non-zero.

**`traplib_spawn_group CMD...`** — Launch `CMD` in an isolated process group. Print child PID to stdout. On cleanup, terminate the entire group including descendant processes.

**`traplib_wait_ready FIFO_PATH TIMEOUT`** — Read one line from a named pipe. Return non-zero if no data arrives within `TIMEOUT` seconds. Remove the FIFO after successful read.

**`traplib_wait_pid PID [TIMEOUT]`** — Wait for `PID` with optional timeout (default 30s). Kill on expiry. Must return promptly when the target process exits, not block for the full timeout period.

**`traplib_run_exclusive LOCKFILE CMD...`** — Execute `CMD` under a mutually exclusive file lock on `LOCKFILE`. Concurrent callers serialize. Lock file removed on script exit. Return `CMD`'s exit status.

**`traplib_critical_section CMD...`** — Execute `CMD` with signal deferral: signals received during `CMD` must not interrupt it but must be re-delivered after `CMD` completes, triggering normal cleanup and signal re-raising.

**`traplib_safe_pipe SRC_CMD SINK_CMD`** — Connect `SRC_CMD`'s stdout to `SINK_CMD`'s stdin via a named pipe. Both processes must be tracked for cleanup and isolated in their own process groups. Return `SINK_CMD`'s exit status. If either side exits, terminate the other. The pipe's temporary directory must be registered for cleanup on any exit path.

**`traplib_supervise MAX_RESTARTS CMD...`** — Run `CMD` in the background. If it exits with non-zero status, restart it (up to `MAX_RESTARTS` times exactly). The supervised child must be tracked for cleanup so it is terminated on signal exit. Return 0 on clean exit, or the last failure's status when restarts are exhausted.

**Verification**: `bash /tests/test.sh`
