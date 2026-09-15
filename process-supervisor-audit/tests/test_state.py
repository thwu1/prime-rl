"""
test_state.py — Verify all bugs are fixed in the process supervisor
and cleanup script, and that root cause analysis is provided.

"""

import os
import re
import signal
import subprocess
import time

import pytest

SUPERVISOR_SRC = "/app/src/supervisor.c"
CLEANUP_SCRIPT = "/app/scripts/cleanup.sh"
ANALYSIS_PATH = "/app/analysis/root_cause.md"
STRACE_FIXED_PATH = "/app/analysis/strace_fixed.log"


def extract_function_body(source, func_name):
    """Extract the body of a C function by name, handling nested braces."""
    pattern = rf"\b{func_name}\s*\([^)]*\)\s*\{{"
    match = re.search(pattern, source)
    if not match:
        return None
    start = source.index("{", match.start())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    return None


# ─── Bug 1: fork() failure in restart_worker → kill(-1) catastrophe ───


class TestForkKillBug:
    """
    BUG: restart_worker() calls fork() without checking for -1.
    If fork() fails (e.g., under memory pressure), -1 is stored as
    the worker PID.  Later, stop_all() calls kill(-1, SIGTERM) which
    sends the signal to every process on the host.
    """

    def test_restart_worker_checks_fork_failure(self):
        """restart_worker must handle fork() returning -1."""
        with open(SUPERVISOR_SRC) as f:
            src = f.read()
        body = extract_function_body(src, "restart_worker")
        assert body is not None, "restart_worker() function not found"

        has_fork = bool(re.search(r"\bfork\s*\(\s*\)", body))
        if has_fork:
            # Direct fork call — the pid variable must be checked for
            # -1 or < 0 (not just any variable like idx)
            assert re.search(r"\bpid\b\s*(==\s*-1|<\s*0)", body), (
                "restart_worker: fork() return (pid) not checked for "
                "failure — pid == -1 or pid < 0 required"
            )
        else:
            # Delegated to spawn_worker (which already checks) — must
            # check spawn_worker's return value
            assert re.search(r"\bspawn_worker\s*\(", body), (
                "restart_worker: must call fork() or spawn_worker()"
            )
            assert re.search(r"(==\s*-1|<\s*0)", body), (
                "restart_worker: spawn_worker() return not checked"
            )

    def test_stop_all_guards_kill_with_positive_pid(self):
        """stop_all must not call kill() with pid <= 0."""
        with open(SUPERVISOR_SRC) as f:
            src = f.read()
        body = extract_function_body(src, "stop_all")
        assert body is not None, "stop_all() function not found"

        if re.search(r"\bkill\s*\(", body):
            assert re.search(r"\.pid\s*>\s*0|pid\s*>\s*0", body), (
                "stop_all: kill() must be guarded by pid > 0 check"
            )


# ─── Bug 2: time() precision loss in event log baseline ───────────


class TestTimingBug:
    """
    BUG: elog_open() uses time(NULL) for the baseline timestamp.
    time() returns whole seconds only — the microsecond fraction is
    lost.  The first event's delta can be off by up to ~1 second.
    """

    def test_elog_open_uses_precise_timestamp(self):
        """elog_open must use gettimeofday() or clock_gettime(), not time()."""
        with open(SUPERVISOR_SRC) as f:
            src = f.read()
        body = extract_function_body(src, "elog_open")
        assert body is not None, "elog_open() function not found"

        assert not re.search(r"\btime\s*\(\s*NULL\s*\)", body), (
            "elog_open: must not use time(NULL) — loses microsecond precision"
        )
        assert re.search(r"(gettimeofday|clock_gettime)\s*\(", body), (
            "elog_open: must use gettimeofday() or clock_gettime()"
        )


# ─── Bug 3: async-signal-unsafe calls in signal handler ──────────


class TestSignalSafety:
    """
    BUG: on_signal() calls elog() which uses fprintf/fflush.
    These are not async-signal-safe — calling them from a signal handler
    can deadlock if the signal interrupts a stdio operation already
    holding the FILE lock.
    """

    def test_signal_handler_is_async_safe(self):
        """on_signal must not call async-signal-unsafe functions."""
        with open(SUPERVISOR_SRC) as f:
            src = f.read()
        body = extract_function_body(src, "on_signal")
        assert body is not None, "on_signal() function not found"

        unsafe_calls = [
            (r"\belog\s*\(", "elog()"),
            (r"\bfprintf\s*\(", "fprintf()"),
            (r"\bprintf\s*\(", "printf()"),
            (r"\bfflush\s*\(", "fflush()"),
            (r"\bvfprintf\s*\(", "vfprintf()"),
            (r"\bvprintf\s*\(", "vprintf()"),
            (r"\bmalloc\s*\(", "malloc()"),
            (r"\bfree\s*\(", "free()"),
            (r"\bfopen\s*\(", "fopen()"),
            (r"\bfclose\s*\(", "fclose()"),
        ]

        for pattern, name in unsafe_calls:
            assert not re.search(pattern, body), (
                f"on_signal: calls {name} which is not async-signal-safe — "
                f"signal handlers must only use sig_atomic_t assignments "
                f"and async-signal-safe syscalls like write() and _exit()"
            )


# ─── Bug 4: orphan process during shutdown race ─────────────────


class TestShutdownSafety:
    """
    BUG: restart_worker() does not check g_stop before forking.
    If SIGTERM arrives during the waitpid/backoff window, restart_worker
    will fork a new child after shutdown has been requested, creating
    an orphan process that is never tracked or cleaned up.
    """

    def test_restart_worker_checks_stop_flag(self):
        """restart_worker must check g_stop before forking."""
        with open(SUPERVISOR_SRC) as f:
            src = f.read()
        body = extract_function_body(src, "restart_worker")
        assert body is not None, "restart_worker() function not found"

        # Find the fork/spawn call position
        fork_match = re.search(r"\b(fork|spawn_worker)\s*\(", body)
        assert fork_match, "restart_worker: must call fork() or spawn_worker()"

        # g_stop must be checked BEFORE the fork/spawn call
        before_spawn = body[: fork_match.start()]
        assert re.search(r"\bg_stop\b", before_spawn), (
            "restart_worker: must check g_stop before spawning "
            "to prevent orphan processes during shutdown"
        )


# ─── Bug 5: unsafe cleanup script ─────────────────────────────────


class TestCleanupScript:
    """
    BUG: cleanup.sh has no error handling, unquoted variables in rm
    commands, and no validation.  If the config file is missing,
    INSTALL_PATH is empty and 'rm -rf /' is effectively run.
    """

    def test_errexit_enabled(self):
        """Script must abort on command failure (set -e)."""
        with open(CLEANUP_SCRIPT) as f:
            content = f.read()
        assert re.search(r"set\s+.*-e|set\s+-o\s+errexit", content), (
            "cleanup.sh: must enable errexit (set -e)"
        )

    def test_pipefail_enabled(self):
        """Script must catch pipeline errors (set -o pipefail)."""
        with open(CLEANUP_SCRIPT) as f:
            content = f.read()
        assert "pipefail" in content, "cleanup.sh: must enable pipefail"

    def test_variables_quoted_in_rm_commands(self):
        """Variable expansions in rm commands must be double-quoted."""
        with open(CLEANUP_SCRIPT) as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Isolate the code before any inline comment
            code = stripped.split("#")[0] if "#" in stripped else stripped
            if "rm " in code and "$" in code:
                assert re.search(r'"\$', code), (
                    f"cleanup.sh: unquoted variable in rm command: {stripped}"
                )

    def test_install_path_validated(self):
        """INSTALL_PATH must be validated as non-empty before rm."""
        with open(CLEANUP_SCRIPT) as f:
            content = f.read()
        assert re.search(
            r"(-z\s+[\"'\$].*INSTALL|"
            r"-n\s+[\"'\$].*INSTALL|"
            r"INSTALL_PATH.*\|\||"
            r"if\s+\[.*INSTALL)",
            content,
        ), "cleanup.sh: INSTALL_PATH must be validated as non-empty"

    def test_config_file_existence_checked(self):
        """Script must check if config file exists before reading."""
        with open(CLEANUP_SCRIPT) as f:
            content = f.read()
        assert re.search(
            r"-[fe]\s+.*(?:CONF|conf)", content, re.IGNORECASE
        ), "cleanup.sh: must check config file existence before reading"


# ─── Compilation check ────────────────────────────────────────────


class TestCompilation:
    """Fixed code must compile without warnings."""

    def test_supervisor_compiles_cleanly(self):
        """supervisor.c must compile with -Wall -Wextra -Werror."""
        result = subprocess.run(
            [
                "gcc",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                "/tmp/supervisor_test_bin",
                SUPERVISOR_SRC,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"
        if os.path.exists("/tmp/supervisor_test_bin"):
            os.remove("/tmp/supervisor_test_bin")


# ─── Runtime smoke test ───────────────────────────────────────────


class TestRuntime:
    """End-to-end: supervisor starts workers and stops cleanly."""

    def test_start_and_graceful_stop(self):
        test_dir = "/tmp/supervisor_e2e"
        os.makedirs(f"{test_dir}/logs", exist_ok=True)

        with open(f"{test_dir}/workers.conf", "w") as f:
            f.write("sleeper\tsleep 300\n")

        # Compile
        result = subprocess.run(
            [
                "gcc",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                f"{test_dir}/supervisor",
                SUPERVISOR_SRC,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Compile failed: {result.stderr}"

        # Start supervisor
        proc = subprocess.Popen(
            [
                f"{test_dir}/supervisor",
                "-c",
                f"{test_dir}/workers.conf",
                "-l",
                f"{test_dir}/logs/events.log",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(1)
        assert proc.poll() is None, "Supervisor exited unexpectedly on startup"

        # Graceful shutdown
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Supervisor did not exit after SIGTERM")

        # Verify event log
        log_path = f"{test_dir}/logs/events.log"
        assert os.path.exists(log_path), "Event log was not created"

        with open(log_path) as f:
            log = f.read()

        assert "supervisor starting" in log, "Missing 'supervisor starting' in log"
        assert "started 'sleeper'" in log, "Missing worker start entry in log"
        assert "shutdown initiated" in log, "Missing 'shutdown initiated' in log"

        # First event delta must be small — time() bug would make it
        # up to ~1s; with gettimeofday() it should be well under 0.1s
        first_line = log.strip().split("\n")[0]
        delta = float(first_line.split()[0])
        assert delta < 0.1, (
            f"First event delta = {delta:.6f}s (expected < 0.1s) — "
            f"likely time() precision bug in elog_open"
        )


# ─── Strace verification ────────────────────────────────────────


class TestStraceVerification:
    """Verify the fix through system call tracing evidence."""

    def test_solver_strace_capture_exists(self):
        """Solver must provide a strace capture of the fixed supervisor."""
        assert os.path.exists(STRACE_FIXED_PATH), (
            f"strace capture not found at {STRACE_FIXED_PATH}"
        )
        with open(STRACE_FIXED_PATH) as f:
            content = f.read()
        assert len(content) > 100, "strace capture appears empty or truncated"

    def test_runtime_strace_kill_safety(self):
        """Independent verification: strace the fixed binary for kill() safety."""
        # Check if strace/ptrace is available in this environment
        check = subprocess.run(
            ["strace", "-e", "trace=none", "/bin/true"],
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            pytest.skip("strace/ptrace not available in this environment")

        test_dir = "/tmp/strace_verify"
        os.makedirs(test_dir, exist_ok=True)

        with open(f"{test_dir}/workers.conf", "w") as f:
            f.write("verifier\tsleep 300\n")

        # Compile
        result = subprocess.run(
            [
                "gcc", "-Wall", "-Wextra", "-Werror",
                "-o", f"{test_dir}/supervisor",
                SUPERVISOR_SRC,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Compile failed: {result.stderr}"

        strace_out = f"{test_dir}/strace.out"

        # Run fixed supervisor under strace, tracing only kill syscalls
        proc = subprocess.Popen(
            [
                "strace", "-f", "-e", "trace=kill",
                "-o", strace_out,
                f"{test_dir}/supervisor",
                "-c", f"{test_dir}/workers.conf",
                "-l", f"{test_dir}/events.log",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(2)
        assert proc.poll() is None, "Supervisor exited unexpectedly under strace"

        # Send SIGTERM for graceful shutdown
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Supervisor did not exit after SIGTERM under strace")

        # Parse strace output for kill() calls with negative PIDs
        with open(strace_out) as f:
            strace_content = f.read()

        kill_calls = re.findall(r"kill\((-?\d+),", strace_content)
        for pid_str in kill_calls:
            pid_val = int(pid_str)
            assert pid_val > 0, (
                f"Fixed supervisor calls kill({pid_val}, ...) — "
                f"catastrophic failure mode not eliminated"
            )


# ─── Root cause analysis ─────────────────────────────────────────


class TestRootCauseAnalysis:
    """Solver must produce a root cause analysis covering all bug classes."""

    def test_analysis_file_exists(self):
        """Root cause analysis must exist at /app/analysis/root_cause.md."""
        assert os.path.exists(ANALYSIS_PATH), (
            "Root cause analysis not found at /app/analysis/root_cause.md"
        )

    def test_analysis_covers_kill_bug(self):
        """Analysis must discuss the kill(-1) catastrophe chain."""
        with open(ANALYSIS_PATH) as f:
            content = f.read().lower()
        has_kill = "kill" in content and (
            "-1" in content or "negative" in content
        )
        assert has_kill, (
            "Analysis must discuss the kill(-1) / kill(negative_pid) catastrophe"
        )

    def test_analysis_covers_timing(self):
        """Analysis must discuss the timestamp precision issue."""
        with open(ANALYSIS_PATH) as f:
            content = f.read().lower()
        has_timing = (
            "time(" in content
            or "timestamp" in content
            or "precision" in content
            or "gettimeofday" in content
            or "clock_gettime" in content
        )
        assert has_timing, (
            "Analysis must discuss the time()/gettimeofday() precision issue"
        )

    def test_analysis_covers_signal_safety(self):
        """Analysis must discuss signal handler async-signal-safety."""
        with open(ANALYSIS_PATH) as f:
            content = f.read().lower()
        has_signal = "signal" in content and (
            "async" in content
            or "safe" in content
            or "handler" in content
            or "reentrant" in content
            or "deadlock" in content
        )
        assert has_signal, (
            "Analysis must discuss signal handler safety / "
            "async-signal-safe violations"
        )

    def test_analysis_references_syscall_evidence(self):
        """Analysis must reference syscall-level or strace evidence."""
        with open(ANALYSIS_PATH) as f:
            content = f.read().lower()
        has_syscall_evidence = (
            "strace" in content
            or "syscall" in content
            or "system call" in content
            or "clone(" in content
            or "wait4" in content
            or "enomem" in content
        )
        assert has_syscall_evidence, (
            "Analysis must reference syscall-level evidence "
            "(strace output, syscall names, errno values)"
        )
