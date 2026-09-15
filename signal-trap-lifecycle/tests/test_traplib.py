"""
Tests for traplib.sh — Signal-safe cleanup lifecycle library.

Verifies: temp dir cleanup (including subshell tracking), signal re-raising,
idempotent cleanup, LIFO handler order, $? preservation, and wait interruptibility.
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
    )

    try:
        if sig is not None:
            if not wait_for_file(ready_file):
                proc.kill()
                proc.wait()
                raise RuntimeError("Script did not write ready file within timeout")
            time.sleep(0.15)  # let script reach blocking state
            proc.send_signal(sig)

        # Use wait() instead of communicate() to avoid blocking on
        # inherited pipe FDs held by background children.
        proc.wait(timeout=timeout)
        return proc.returncode, workdir
    except subprocess.TimeoutExpired:
        proc.kill()
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
            f"Temp dir {td} still exists after normal exit. "
            "traplib_mktemp_dir inside $() runs in a subshell — array "
            "modifications are lost in the parent. Use a file-based registry."
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
            f"Expected signal kill (rc={-signal.SIGTERM}), got rc={rc}. "
            "Cleanup must re-raise SIGTERM (trap - TERM; kill -s TERM $$), "
            "not call exit."
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
            f"Expected signal kill (rc={-signal.SIGINT}), got rc={rc}."
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
            f"Expected signal kill (rc={-signal.SIGHUP}), got rc={rc}."
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
            f"Cleanup handlers ran {count} times, expected exactly 1. "
            "Both the signal trap and the EXIT trap are calling cleanup — "
            "add an idempotency guard and clear the EXIT trap on signal entry."
        )


# ---------------------------------------------------------------------------
# Handler execution order
# ---------------------------------------------------------------------------

class TestHandlerOrder:
    """Handlers must execute in LIFO (reverse registration) order."""

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
            f"Expected LIFO order [THIRD, SECOND, FIRST], got {lines}. "
            "Iterate the handler array in reverse."
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
            f"Expected _TRAPLIB_SAVED_STATUS=7, got {saved}. "
            "Capture $? on the very first line of _traplib_run_cleanup, "
            "before any 'local' declaration clobbers it."
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
            f"Expected _TRAPLIB_SAVED_STATUS=42, got {saved}."
        )


# ---------------------------------------------------------------------------
# Wait interruptibility
# ---------------------------------------------------------------------------

class TestWaitInterruptibility:
    """
    traplib_wait_pid must use 'wait' (an interruptible builtin), not a
    foreground 'sleep' (an external command that defers signal handling).
    """

    def test_signal_during_wait_pid_handled_promptly(self, workdir):
        start = time.time()
        try:
            rc, _ = run_test_script(workdir, '''
source /app/traplib.sh
traplib_init
sleep 300 </dev/null >/dev/null 2>&1 &
child=$!
traplib_push_handler "kill $child 2>/dev/null; wait $child 2>/dev/null"
echo "READY" > __READY__
traplib_wait_pid "$child" 300
''', sig=signal.SIGTERM, timeout=10)
            elapsed = time.time() - start
            assert elapsed < 8, (
                f"Process took {elapsed:.1f}s to respond to SIGTERM. "
                "traplib_wait_pid must use 'wait' (interruptible builtin) "
                "instead of 'sleep' (external command that defers signals)."
            )
        except subprocess.TimeoutExpired:
            pytest.fail(
                "Process did not exit within 10s after SIGTERM. "
                "traplib_wait_pid uses a foreground 'sleep' that blocks "
                "signal delivery. Replace with 'wait $pid'."
            )
