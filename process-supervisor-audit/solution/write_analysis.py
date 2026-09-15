#!/usr/bin/env python3
"""
write_analysis.py — Write root cause analysis to /app/analysis/root_cause.md

"""

import os

ANALYSIS_DIR = "/app/analysis"
ANALYSIS_PATH = os.path.join(ANALYSIS_DIR, "root_cause.md")

os.makedirs(ANALYSIS_DIR, exist_ok=True)

analysis = """\
# Root Cause Analysis — prod-web-037 Incident

## Bug 1: fork() failure leading to kill(-1) catastrophe

**Root cause**: `restart_worker()` calls `fork()` directly without checking for
a return value of -1 (failure). When the host was under memory pressure during
the deployment, `fork()` failed and returned -1. This value was stored in the
worker slot's `pid` field. When `stop_all()` later iterated over active worker
slots, it called `kill(-1, SIGTERM)`. On Linux, `kill(-1, sig)` sends the signal
to every process the caller has permission to signal, except init (pid 1) and
the caller itself. Since the supervisor runs as root and outside a PID namespace,
this killed every process on the host — sshd, cron, rsyslog, monitoring agents,
and all application workers.

**Strace evidence**: The strace capture shows the syscall chain:
`clone(...) = -1 ENOMEM` (fork failure at kernel level) followed by
`write(4, "... pid=-1 ...")` (invalid PID stored and logged), and ultimately
`kill(-1, SIGTERM) = 0` in `stop_all()` — the catastrophic broadcast kill.
The subsequent `kill(1290, SIGTERM) = -1 ESRCH` and `kill(1291, SIGTERM) = -1 ESRCH`
confirm that the other workers were already dead from the kill(-1) broadcast.

**Note**: `spawn_worker()` correctly checks for `fork() == -1`, but
`restart_worker()` bypasses `spawn_worker()` and calls `fork()` directly
without the same check.

**Fix**: Added `if (pid == -1) { return -1; }` after the `fork()` call in
`restart_worker()`. Also added a `pid > 0` guard on the `kill()` call in
`stop_all()` as defense-in-depth.

## Bug 2: Timestamp precision loss in event log

**Root cause**: `elog_open()` initializes the baseline timestamp using
`time(NULL)`, which returns whole seconds only (truncating the sub-second
component). Subsequent calls to `elog()` use `gettimeofday()` which provides
microsecond precision. The first delta computation subtracts a truncated
baseline from a precise current time, producing a spurious offset of up to
~1 second. This was observed in the incident log as a first-entry delta of
0.847293 seconds despite the supervisor starting within milliseconds.

**Fix**: Replaced `time(NULL)` with `gettimeofday()` in `elog_open()` to
capture the baseline with microsecond precision, matching the resolution
used in `elog()`.

## Bug 3: Async-signal-unsafe calls in signal handler

**Root cause**: The `on_signal()` signal handler calls `elog()`, which
internally uses `fprintf()` and `fflush()`. These are not async-signal-safe
functions. If a signal arrives while `elog()` is mid-write (holding the stdio
FILE lock), the signal handler's `elog()` call attempts to acquire the same
lock, causing a deadlock. This explains the intermittent 5-10 second "hangs"
observed during high worker churn — the deadlock resolves only when a
subsequent signal (e.g., SIGCHLD) interrupts the blocked call.

**Strace evidence**: The strace capture shows `gettimeofday()` and `write(4, ...)`
syscalls occurring between `--- SIGTERM ---` delivery and `rt_sigreturn()`.
These syscalls originate from the `elog()` call within the signal handler —
while `write()` itself is async-signal-safe, the `fprintf()`/`fflush()` path
involves stdio buffer locking which is not, creating the deadlock risk.

**Fix**: Removed the `elog()` call from `on_signal()`. The signal handler
now only sets the `g_stop` volatile sig_atomic_t flag, which is
async-signal-safe. Shutdown logging is handled by `main()` after the
run loop exits.

## Bug 4: Orphan process spawning during shutdown

**Root cause**: `restart_worker()` does not check `g_stop` before calling
`fork()`. If SIGTERM arrives during the `waitpid()` call for the dying child
or during the exponential back-off `sleep()`, `restart_worker()` will still
fork a new child process. This child will never be properly tracked or
cleaned up because the main loop exits immediately after `g_stop` is set.

**Fix**: Added `if (g_stop) return -1;` before the `fork()` call in
`restart_worker()` to abort the restart sequence if shutdown has been
requested.

## Bug 5: Unsafe cleanup script

**Root cause**: `cleanup.sh` has multiple safety issues:
- No `set -e` or `pipefail` — errors are silently ignored
- No validation that the config file exists — if missing, `INSTALL_PATH`
  is empty
- Unquoted variable expansions in `rm` commands — with empty
  `INSTALL_PATH`, commands like `rm -rf $INSTALL_PATH/bin/` expand to
  `rm -rf /bin/`, deleting system directories

**Fix**: Added `set -euo pipefail`, config file existence check (`-f` test),
`INSTALL_PATH` non-empty validation, and double-quoted all variable
expansions in `rm` commands.

## Incident Chain of Events

1. Deployment caused memory spike (old + new binaries coexisting)
2. Kernel OOM killer activated, killing php-fpm workers (NOT system services)
3. Supervisor detected worker exits, called `restart_worker()`
4. `fork()` failed due to memory exhaustion, returned -1
5. -1 stored as worker PID in the slot table (no error check)
6. On next shutdown/restart cycle, `kill(-1, SIGTERM)` sent
7. All processes except init and supervisor killed
8. sshd, cron, monitoring — all terminated by SIGTERM
9. Host unreachable, required out-of-band console access

**Red herrings eliminated**:
- OOM killer: killed php-fpm only, used SIGKILL not SIGTERM
- NFS errors: downstream symptom, backup cron job was killed
"""

with open(ANALYSIS_PATH, "w") as f:
    f.write(analysis)

print(f"Wrote root cause analysis to {ANALYSIS_PATH}")
