"""
Tests for traplib.sh — Signal-safe process lifecycle management library.

Verifies: temp dir cleanup (including subshell tracking), signal re-raising,
idempotent cleanup, handler ordering, $? preservation, wait_pid semantics,
process group management, FIFO readiness, exclusive file locking,
critical section signal deferral, errexit compatibility, double-init safety,
safe_pipe lifecycle management, and supervised process restart/cleanup.
"""


import subprocess
import os
import time
import signal
import tempfile
import shutil
import pytest


TRAPLIB_PATH = "/app/traplib.sh"


@pytest.fixture
def workdir():
    """Create a temp directory for each test, cleaned up afterwards."""
    d = tempfile.mkdtemp(prefix="traptest_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def wait_for_file(path, timeout=10):
    """Poll until a file appears on disk."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            time.sleep(0.05)
            return True
        time.sleep(0.02)
    return False


def read_file(path):
    with open(path) as f:
        return f.read().strip()


def run_test_script(workdir, script_body, sig=None, timeout=15):
    """
    Write a bash script into workdir, run it, optionally send a signal.

    Placeholders in script_body:
      __WORKDIR__ -> workdir path
      __READY__   -> path of the ready-signal file

    Returns (returncode, workdir).
    Raises subprocess.TimeoutExpired if the script doesn't exit in time.
    """
    script_path = os.path.join(workdir, "test_run.sh")
    ready_file = os.path.join(workdir, "ready")

    full_script = (
        "#!/bin/bash\n"
        + script_body
            .replace("__WORKDIR__", workdir)
            .replace("__READY__", ready_file)
    )

    with open(script_path, "w") as f:
        f.write(full_script)
    os.chmod(script_path, 0o755)

    proc = subprocess.Popen(
        ["bash", script_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    try:
        if sig is not None:
            if not wait_for_file(ready_file):
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise RuntimeError("Script did not write ready file within timeout")
            time.sleep(0.15)
            proc.send_signal(sig)

        proc.wait(timeout=timeout)
        return proc.returncode, workdir
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise


# ---------------------------------------------------------------------------
# Temp directory cleanup
# ---------------------------------------------------------------------------

class TestTempDirCleanup:
    """Temp dirs created via traplib_mktemp_dir must be removed on any exit."""

    def test_normal_exit_cleans_tempdir(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
d=$(traplib_mktemp_dir)
echo "$d" > __WORKDIR__/td_path
exit 0
''')
        td = read_file(os.path.join(workdir, "td_path"))
        assert td.startswith("/tmp/traplib."), f"Unexpected temp dir path: {td}"
        assert not os.path.exists(td), (
            f"Temp dir {td} still exists after normal exit"
        )

    def test_error_exit_cleans_tempdir(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
d=$(traplib_mktemp_dir)
echo "$d" > __WORKDIR__/td_path
exit 1
''')
        td = read_file(os.path.join(workdir, "td_path"))
        assert not os.path.exists(td), f"Temp dir {td} not cleaned on error exit"

    def test_sigterm_cleans_tempdir(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
d=$(traplib_mktemp_dir)
echo "$d" > __WORKDIR__/td_path
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGTERM)
        td = read_file(os.path.join(workdir, "td_path"))
        assert not os.path.exists(td), f"Temp dir {td} not cleaned on SIGTERM"

    def test_multiple_tempdirs_all_cleaned(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
d1=$(traplib_mktemp_dir)
d2=$(traplib_mktemp_dir)
d3=$(traplib_mktemp_dir)
echo "$d1" > __WORKDIR__/td1
echo "$d2" > __WORKDIR__/td2
echo "$d3" > __WORKDIR__/td3
exit 0
''')
        for name in ("td1", "td2", "td3"):
            td = read_file(os.path.join(workdir, name))
            assert not os.path.exists(td), (
                f"Temp dir {td} ({name}) not cleaned up"
            )


# ---------------------------------------------------------------------------
# Signal re-raising
# ---------------------------------------------------------------------------

class TestSignalReraising:
    """
    After signal cleanup, the process must re-raise the signal with default
    disposition so the parent observes signal termination (WIFSIGNALED),
    not a normal exit with code 128+N.

    Python subprocess reports signal kills as negative return codes.
    """

    def test_sigterm_produces_signal_kill(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGTERM)
        assert rc == -signal.SIGTERM, (
            f"Expected signal kill (rc={-signal.SIGTERM}), got rc={rc}"
        )

    def test_sigint_produces_signal_kill(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGINT)
        assert rc == -signal.SIGINT, (
            f"Expected signal kill (rc={-signal.SIGINT}), got rc={rc}"
        )

    def test_sighup_produces_signal_kill(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGHUP)
        assert rc == -signal.SIGHUP, (
            f"Expected signal kill (rc={-signal.SIGHUP}), got rc={rc}"
        )


# ---------------------------------------------------------------------------
# Cleanup idempotency
# ---------------------------------------------------------------------------

class TestCleanupIdempotency:
    """Signal trap + EXIT trap must not cause handlers to run twice."""

    def test_cleanup_runs_exactly_once(self, workdir):
        count_file = os.path.join(workdir, "count")
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
echo "0" > __WORKDIR__/count
traplib_push_handler 'c=$(cat __WORKDIR__/count); echo $((c+1)) > __WORKDIR__/count'
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGTERM)
        count = int(read_file(count_file))
        assert count == 1, (
            f"Cleanup handlers ran {count} times, expected exactly 1"
        )


# ---------------------------------------------------------------------------
# Handler execution order
# ---------------------------------------------------------------------------

class TestHandlerOrder:
    """Handlers must execute in reverse registration order (LIFO)."""

    def test_lifo_order(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
: > __WORKDIR__/order
traplib_push_handler 'echo "FIRST" >> __WORKDIR__/order'
traplib_push_handler 'echo "SECOND" >> __WORKDIR__/order'
traplib_push_handler 'echo "THIRD" >> __WORKDIR__/order'
exit 0
''')
        lines = read_file(os.path.join(workdir, "order")).split("\n")
        assert lines == ["THIRD", "SECOND", "FIRST"], (
            f"Expected LIFO order [THIRD, SECOND, FIRST], got {lines}"
        )


# ---------------------------------------------------------------------------
# Exit status preservation
# ---------------------------------------------------------------------------

class TestStatusPreservation:
    """
    _TRAPLIB_SAVED_STATUS must hold the $? that was in effect when
    cleanup was triggered (e.g. 7 after '(exit 7)' at end of script).
    """

    def test_exit_status_preserved_on_normal_exit(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_push_handler 'echo "$_TRAPLIB_SAVED_STATUS" > __WORKDIR__/saved'
(exit 7)
''')
        saved = int(read_file(os.path.join(workdir, "saved")))
        assert saved == 7, (
            f"Expected _TRAPLIB_SAVED_STATUS=7, got {saved}"
        )

    def test_exit_status_preserved_on_explicit_exit(self, workdir):
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_push_handler 'echo "$_TRAPLIB_SAVED_STATUS" > __WORKDIR__/saved'
exit 42
''')
        saved = int(read_file(os.path.join(workdir, "saved")))
        assert saved == 42, (
            f"Expected _TRAPLIB_SAVED_STATUS=42, got {saved}"
        )


# ---------------------------------------------------------------------------
# Wait PID semantics
# ---------------------------------------------------------------------------

class TestWaitPid:
    """
    traplib_wait_pid must wait for the target process, not the timer.
    It must return promptly when the target exits early.
    """

    def test_returns_when_target_exits(self, workdir):
        """wait_pid returns promptly when target exits, does not block for timeout."""
        start = time.time()
        try:
            rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
sleep 0.5 &
child=$!
traplib_wait_pid "$child" 60
echo "DONE" > __WORKDIR__/done
exit 0
''', timeout=15)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "wait_pid blocked for full timeout instead of returning when target exited"
            )

        elapsed = time.time() - start
        assert os.path.exists(os.path.join(workdir, "done")), \
            "wait_pid did not return"
        assert elapsed < 5, (
            f"wait_pid blocked for {elapsed:.1f}s (target exited at ~0.5s)"
        )


# ---------------------------------------------------------------------------
# Process group management
# ---------------------------------------------------------------------------

class TestProcessGroupManagement:
    """
    traplib_spawn_group must isolate the command in its own process group.
    Cleanup must kill the entire process group so grandchildren are not orphaned.
    """

    def test_spawn_group_kills_entire_group(self, workdir):
        worker_script = os.path.join(workdir, "worker.sh")
        with open(worker_script, "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"sleep 300 </dev/null >/dev/null 2>&1 &\n"
                f"echo $! > {workdir}/grandchild_pid\n"
                f"echo READY > {workdir}/ready\n"
                "wait\n"
            )
        os.chmod(worker_script, 0o755)

        rc, _ = run_test_script(workdir, f'''
source /app/traplib.sh
traplib_init
traplib_spawn_group bash {worker_script} > /dev/null
while [ ! -f __READY__ ]; do sleep 0.05; done
sleep 0.3
exit 0
''')
        time.sleep(0.5)
        grandchild_pid = int(read_file(os.path.join(workdir, "grandchild_pid")))
        try:
            os.kill(grandchild_pid, 0)
            alive = True
        except OSError:
            alive = False
        # Always clean up leaked grandchild
        try:
            os.kill(grandchild_pid, signal.SIGKILL)
        except OSError:
            pass
        assert not alive, (
            f"Grandchild process {grandchild_pid} still alive after cleanup"
        )

    def test_spawn_group_returns_pid(self, workdir):
        """traplib_spawn_group must print the child PID to stdout."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_spawn_group sleep 5 > __WORKDIR__/spawned_pid
sleep 0.3
exit 0
''')
        pid_str = read_file(os.path.join(workdir, "spawned_pid"))
        assert pid_str.strip().isdigit(), f"Expected numeric PID, got '{pid_str}'"


# ---------------------------------------------------------------------------
# FIFO readiness
# ---------------------------------------------------------------------------

class TestFifoReadiness:
    """
    traplib_wait_ready must handle named pipes with timeout.
    """

    def test_wait_ready_receives_data(self, workdir):
        """wait_ready reads data from a named pipe when a writer is available."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
fifo="__WORKDIR__/test_fifo"
mkfifo "$fifo"
echo "READY_SIGNAL" > "$fifo" &
result=$(traplib_wait_ready "$fifo" 5)
echo "$result" > __WORKDIR__/result
exit 0
''')
        result = read_file(os.path.join(workdir, "result"))
        assert result == "READY_SIGNAL", f"Expected 'READY_SIGNAL', got '{result}'"

    def test_wait_ready_times_out(self, workdir):
        """wait_ready must return non-zero if nobody writes within timeout."""
        start = time.time()
        try:
            rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
fifo="__WORKDIR__/test_fifo"
mkfifo "$fifo"
traplib_wait_ready "$fifo" 2
echo "$?" > __WORKDIR__/rc
exit 0
''', timeout=15)
            elapsed = time.time() - start
            assert elapsed < 10, (
                f"wait_ready blocked for {elapsed:.1f}s instead of timing out at 2s"
            )
            rc_val = int(read_file(os.path.join(workdir, "rc")))
            assert rc_val != 0, "wait_ready should return non-zero on timeout"
        except subprocess.TimeoutExpired:
            pytest.fail(
                "wait_ready blocked indefinitely — needs timeout support"
            )

    def test_wait_ready_cleans_fifo(self, workdir):
        """FIFO must be removed after a successful read."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
fifo="__WORKDIR__/test_fifo"
mkfifo "$fifo"
echo "READY" > "$fifo" &
traplib_wait_ready "$fifo" 5 > /dev/null
if [ -e "$fifo" ]; then
    echo "EXISTS" > __WORKDIR__/fifo_state
else
    echo "REMOVED" > __WORKDIR__/fifo_state
fi
exit 0
''')
        state = read_file(os.path.join(workdir, "fifo_state"))
        assert state == "REMOVED", "FIFO should be removed after successful read"


# ---------------------------------------------------------------------------
# Exclusive file locking
# ---------------------------------------------------------------------------

class TestRunExclusive:
    """traplib_run_exclusive must provide mutual exclusion and clean up lock files."""

    def test_mutual_exclusion(self, workdir):
        """Two concurrent callers with the same lock file must serialize."""
        counter = os.path.join(workdir, "counter")
        worker = os.path.join(workdir, "inc.sh")
        with open(counter, "w") as f:
            f.write("0")
        with open(worker, "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"c=$(cat {counter})\n"
                "sleep 0.5\n"
                f"echo $((c + 1)) > {counter}\n"
            )
        os.chmod(worker, 0o755)

        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
lockfile="__WORKDIR__/testlock"
(traplib_run_exclusive "$lockfile" bash __WORKDIR__/inc.sh) &
sleep 0.1
(traplib_run_exclusive "$lockfile" bash __WORKDIR__/inc.sh) &
wait
exit 0
''', timeout=15)
        final = int(read_file(counter))
        assert final == 2, (
            f"Counter is {final}, expected 2. "
            "Concurrent traplib_run_exclusive calls must serialize."
        )

    def test_lockfile_cleaned_on_exit(self, workdir):
        """Lock file must be removed when the script exits normally."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_run_exclusive __WORKDIR__/testlock2 true
exit 0
''')
        lockfile = os.path.join(workdir, "testlock2")
        assert not os.path.exists(lockfile), (
            "Lock file still exists after normal exit"
        )

    def test_lockfile_cleaned_on_signal(self, workdir):
        """Lock file must be removed when the script receives SIGTERM."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_run_exclusive __WORKDIR__/testlock3 true
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGTERM)
        lockfile = os.path.join(workdir, "testlock3")
        assert not os.path.exists(lockfile), (
            "Lock file still exists after SIGTERM"
        )


# ---------------------------------------------------------------------------
# Critical section signal deferral
# ---------------------------------------------------------------------------

class TestCriticalSection:
    """
    traplib_critical_section must defer signals during command execution
    and re-deliver them afterwards, triggering cleanup and signal re-raising.
    """

    def test_signal_deferred_and_redelivered(self, workdir):
        """Signal during critical section: deferred, section completes, then signal kills."""
        try:
            rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
d=$(traplib_mktemp_dir)
echo "$d" > __WORKDIR__/td_path
traplib_critical_section bash -c '
    echo "READY" > __READY__
    sleep 2
    echo "DONE" > __WORKDIR__/section_done
'
echo "UNREACHABLE" > __WORKDIR__/unreachable
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGTERM, timeout=15)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "Signal was silently lost during critical section — "
                "process hung instead of being killed after section completed"
            )

        assert os.path.exists(os.path.join(workdir, "section_done")), \
            "Critical section was interrupted by signal (signal not deferred)"
        assert not os.path.exists(os.path.join(workdir, "unreachable")), \
            "Script continued after critical section (deferred signal not re-delivered)"
        assert rc == -signal.SIGTERM, (
            f"Expected signal kill (rc={-signal.SIGTERM}), got rc={rc}"
        )
        td = read_file(os.path.join(workdir, "td_path"))
        assert not os.path.exists(td), \
            "Temp dir not cleaned up after deferred signal"


# ---------------------------------------------------------------------------
# Errexit (set -e) compatibility
# ---------------------------------------------------------------------------

class TestErrexitCompat:
    """Library cleanup must work correctly with set -e enabled."""

    def test_cleanup_completes_with_errexit(self, workdir):
        """Handlers returning non-zero must not abort cleanup under set -e."""
        rc, _ = run_test_script(workdir, '''
set -e
source /app/traplib.sh
traplib_init
d=$(traplib_mktemp_dir)
echo "$d" > __WORKDIR__/td_path
traplib_push_handler 'false'
traplib_push_handler 'echo "SECOND_RAN" > __WORKDIR__/second'
(exit 0)
exit 0
''')
        td = read_file(os.path.join(workdir, "td_path"))
        assert not os.path.exists(td), \
            "Temp dir not cleaned up — cleanup aborted by errexit after failing handler"
        assert os.path.exists(os.path.join(workdir, "second")), \
            "Second handler did not run — cleanup aborted by errexit"

    def test_cleanup_and_signal_under_errexit(self, workdir):
        """Failing handler under set -e must not prevent signal re-raising."""
        rc, _ = run_test_script(workdir, '''
set -e
source /app/traplib.sh
traplib_init
traplib_push_handler 'false'
echo "READY" > __READY__
sleep 300 </dev/null >/dev/null 2>&1 &
wait $!
''', sig=signal.SIGTERM)
        assert rc == -signal.SIGTERM, (
            f"Expected signal kill under set -e (rc={-signal.SIGTERM}), got rc={rc}. "
            "Errexit likely aborted cleanup before signal re-raise."
        )


# ---------------------------------------------------------------------------
# Double initialization safety
# ---------------------------------------------------------------------------

class TestDoubleInit:
    """Calling traplib_init twice must not lose tracked resources."""

    def test_reinit_preserves_state(self, workdir):
        """Temp dirs tracked before re-init must still be cleaned up."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
d=$(traplib_mktemp_dir)
echo "$d" > __WORKDIR__/td_path
traplib_init
exit 0
''')
        td = read_file(os.path.join(workdir, "td_path"))
        assert not os.path.exists(td), (
            "Temp dir leaked after traplib_init called twice — "
            "re-initialization replaced the registry, losing tracked resources"
        )


# ---------------------------------------------------------------------------
# Safe pipe lifecycle management
# ---------------------------------------------------------------------------

class TestSafePipe:
    """
    traplib_safe_pipe must manage both sides of a pipeline with proper
    process tracking, exit status semantics, and cleanup.
    """

    def test_data_flows_through_pipe(self, workdir):
        """Data written by producer is received by consumer."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_safe_pipe 'echo HELLO_PIPE' 'cat > __WORKDIR__/pipe_out'
sleep 0.3
exit 0
''')
        out_file = os.path.join(workdir, "pipe_out")
        wait_for_file(out_file, timeout=3)
        assert os.path.exists(out_file), "Consumer output file not created"
        result = read_file(out_file)
        assert result == "HELLO_PIPE", f"Expected 'HELLO_PIPE', got '{result}'"

    def test_returns_sink_exit_status(self, workdir):
        """Must return consumer's exit status, not producer's."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_safe_pipe 'echo data; exit 0' 'cat > /dev/null; exit 37'
echo $? > __WORKDIR__/pipe_rc
exit 0
''')
        pipe_rc = int(read_file(os.path.join(workdir, "pipe_rc")))
        assert pipe_rc == 37, (
            f"Expected sink exit status 37, got {pipe_rc}. "
            "safe_pipe must return consumer's exit status, not producer's."
        )

    def test_pipe_processes_cleaned_on_signal(self, workdir):
        """Both pipe processes must be tracked and killed on signal exit."""
        producer_script = os.path.join(workdir, "producer.sh")
        with open(producer_script, "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"echo $$ > {workdir}/prod_pid\n"
                f"echo READY > {workdir}/ready\n"
                "sleep 300\n"
            )
        os.chmod(producer_script, 0o755)

        rc, _ = run_test_script(workdir, f'''
source /app/traplib.sh
traplib_init
traplib_safe_pipe "bash {producer_script}" "cat >/dev/null; sleep 300"
''', sig=signal.SIGTERM, timeout=10)
        time.sleep(0.5)
        prod_pid_file = os.path.join(workdir, "prod_pid")
        assert os.path.exists(prod_pid_file), "Producer PID file not written"
        prod_pid = int(read_file(prod_pid_file))
        try:
            os.kill(prod_pid, 0)
            alive = True
        except OSError:
            alive = False
        # Always clean up leaked process
        try:
            os.kill(prod_pid, signal.SIGKILL)
        except OSError:
            pass
        assert not alive, (
            f"Pipe producer {prod_pid} still alive after SIGTERM — "
            "pipe processes not tracked for cleanup"
        )


# ---------------------------------------------------------------------------
# Supervised process management
# ---------------------------------------------------------------------------

class TestSupervise:
    """
    traplib_supervise must restart failing commands, respect the restart
    limit, and track supervised children for cleanup.
    """

    def test_restarts_on_failure(self, workdir):
        """A crashing command is restarted at least once."""
        counter = os.path.join(workdir, "run_count")
        with open(counter, "w") as f:
            f.write("0")
        failing_script = os.path.join(workdir, "failing.sh")
        with open(failing_script, "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"c=$(<{counter})\n"
                f"echo $((c+1)) > {counter}\n"
                "exit 1\n"
            )
        os.chmod(failing_script, 0o755)

        rc, _ = run_test_script(workdir, f'''
source /app/traplib.sh
traplib_init
traplib_supervise 3 bash {failing_script}
exit $?
''', timeout=15)
        count = int(read_file(counter))
        assert count >= 2, (
            f"Expected command to be restarted at least once, got {count} executions"
        )

    def test_respects_max_restarts(self, workdir):
        """With max_restarts=2, exactly 3 executions (initial + 2 restarts)."""
        counter = os.path.join(workdir, "run_count")
        with open(counter, "w") as f:
            f.write("0")
        failing_script = os.path.join(workdir, "failing.sh")
        with open(failing_script, "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"c=$(<{counter})\n"
                f"echo $((c+1)) > {counter}\n"
                "exit 1\n"
            )
        os.chmod(failing_script, 0o755)

        rc, _ = run_test_script(workdir, f'''
source /app/traplib.sh
traplib_init
traplib_supervise 2 bash {failing_script}
exit $?
''', timeout=15)
        count = int(read_file(counter))
        assert count == 3, (
            f"With max_restarts=2, expected 3 executions (initial + 2 restarts), "
            f"got {count}"
        )

    def test_supervised_child_killed_on_signal(self, workdir):
        """Supervised child must be tracked for cleanup on signal exit."""
        rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
traplib_supervise 5 bash -c 'echo $$ > __WORKDIR__/child_pid; echo READY > __READY__; sleep 300'
''', sig=signal.SIGTERM, timeout=10)
        time.sleep(0.5)
        pid_file = os.path.join(workdir, "child_pid")
        assert os.path.exists(pid_file), "Child PID file not written"
        child_pid = int(read_file(pid_file))
        try:
            os.kill(child_pid, 0)
            alive = True
        except OSError:
            alive = False
        # Always clean up leaked process
        try:
            os.kill(child_pid, signal.SIGKILL)
        except OSError:
            pass
        assert not alive, (
            f"Supervised child {child_pid} still alive after SIGTERM — "
            "child not tracked for cleanup"
        )
