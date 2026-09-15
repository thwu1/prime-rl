#!/usr/bin/env python3
"""
fix_supervisor.py — Fix five bugs in /app/src/supervisor.c

Bug 1 (kill -1): restart_worker() stores fork()'s return value
    without checking for -1.  Add the missing error check.

Bug 2 (defense-in-depth): stop_all() calls kill() without verifying
    pid > 0.  Add a guard.

Bug 3 (timing): elog_open() uses time(NULL) which truncates the
    microsecond fraction.  Replace with gettimeofday().

Bug 4 (signal safety): on_signal() calls elog() which uses
    fprintf/fflush — async-signal-unsafe.  Remove the call.

Bug 5 (shutdown race): restart_worker() does not check g_stop
    before forking.  Add the check.

"""

import sys

SRC = "/app/src/supervisor.c"

with open(SRC) as f:
    src = f.read()

original = src

# ── Bug 3: Replace time(NULL) with gettimeofday() in elog_open ──

old_timing = "    g_elog_ts = (double)time(NULL);"
new_timing = """\
    struct timeval init_tv;
    gettimeofday(&init_tv, NULL);
    g_elog_ts = (double)init_tv.tv_sec + (double)init_tv.tv_usec / 1e6;"""

if old_timing not in src:
    print("WARNING: timing bug pattern not found — may already be fixed",
          file=sys.stderr)
else:
    src = src.replace(old_timing, new_timing)
    print("Fixed: elog_open() now uses gettimeofday() for baseline timestamp")

# ── Bug 4: Remove async-signal-unsafe elog() call from on_signal ──

old_signal = """\
static void on_signal(int sig) {
    elog("received signal %d, initiating shutdown", sig);
    g_stop = 1;
}"""

new_signal = """\
static void on_signal(int sig) {
    (void)sig;
    g_stop = 1;
}"""

if old_signal not in src:
    print("WARNING: signal handler pattern not found — may already be fixed",
          file=sys.stderr)
else:
    src = src.replace(old_signal, new_signal)
    print("Fixed: on_signal() no longer calls async-signal-unsafe functions")

# ── Bugs 1 & 5: Add g_stop check and fork() failure check in restart_worker ──

old_fork = """\
    /* Fork a replacement process. */
    pid_t pid = fork();
    if (pid == 0) {"""

new_fork = """\
    /* Abort restart if shutdown was requested during back-off. */
    if (g_stop) return -1;

    /* Fork a replacement process. */
    pid_t pid = fork();
    if (pid == -1) {
        fprintf(stderr, "restart_worker: fork: %s\\n", strerror(errno));
        return -1;
    }
    if (pid == 0) {"""

if old_fork not in src:
    print("WARNING: fork bug pattern not found — may already be fixed",
          file=sys.stderr)
else:
    src = src.replace(old_fork, new_fork)
    print("Fixed: restart_worker() now checks g_stop and fork() return for -1")

# ── Bug 2: Guard kill() in stop_all with pid > 0 ──

old_stop = """\
        if (g_slots[i].active) {
            kill(g_slots[i].pid, SIGTERM);"""

new_stop = """\
        if (g_slots[i].active && g_slots[i].pid > 0) {
            kill(g_slots[i].pid, SIGTERM);"""

if old_stop not in src:
    print("WARNING: stop_all guard pattern not found — may already be fixed",
          file=sys.stderr)
else:
    src = src.replace(old_stop, new_stop)
    print("Fixed: stop_all() now guards kill() with pid > 0")

if src == original:
    print("No changes made — all patterns already fixed or not found",
          file=sys.stderr)
    sys.exit(1)

with open(SRC, "w") as f:
    f.write(src)

print(f"Wrote fixed source to {SRC}")
