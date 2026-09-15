
import os
import signal
import subprocess
import time
import pytest

PTYSESSION = "/app/ptysession"
REPORTER = "/app/reporter"


def run_session(cmd, timeout=10):
    """Run ptysession with the given command and return the result."""
    return subprocess.run(
        [PTYSESSION] + cmd,
        capture_output=True, text=True, timeout=timeout
    )


def parse_report(stdout):
    """Parse reporter key=value output into a dict."""
    d = {}
    for line in stdout.replace('\r\n', '\n').replace('\r', '').strip().split('\n'):
        line = line.strip()
        if '=' in line:
            k, v = line.split('=', 1)
            d[k.strip()] = v.strip()
    return d


class TestPtySession:

    @classmethod
    def setup_class(cls):
        r = subprocess.run(["make", "-C", "/app"], capture_output=True, text=True)
        assert r.returncode == 0, f"Build failed:\n{r.stderr}"
        assert os.path.isfile(PTYSESSION), "ptysession binary not found"
        assert os.path.isfile(REPORTER), "reporter binary not found"

    def _get_report(self):
        try:
            r = run_session([REPORTER], timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("ptysession hung — cannot retrieve reporter output")
        assert r.returncode == 0, (
            f"Reporter exited with code {r.returncode}:\n{r.stderr}"
        )
        d = parse_report(r.stdout)
        assert 'PID' in d, f"Cannot parse reporter output:\n{r.stdout!r}"
        return d

    # --- Core session properties ---

    def test_tool_exits_promptly(self):
        """ptysession must exit within 5 seconds after the child finishes."""
        start = time.time()
        try:
            r = run_session(["/bin/echo", "done"], timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "ptysession did not exit within 10 s after child finished"
            )
        elapsed = time.time() - start
        assert elapsed < 5, f"Took {elapsed:.1f}s — expected < 5 s"
        assert r.returncode == 0

    def test_new_session_created(self):
        """Child must be a session leader: SID == PID."""
        d = self._get_report()
        assert d['SID'] == d['PID'], (
            f"SID={d['SID']} != PID={d['PID']}; "
            "child is not running in its own session"
        )

    def test_new_process_group(self):
        """Child must head its own process group: PGID == PID."""
        d = self._get_report()
        assert d['PGID'] == d['PID'], (
            f"PGID={d['PGID']} != PID={d['PID']}"
        )

    def test_has_controlling_terminal(self):
        """Child must have a controlling terminal (open /dev/tty succeeds)."""
        d = self._get_report()
        assert d.get('HAS_CTTY') == 'yes', (
            "Child has no controlling terminal"
        )

    def test_stdin_is_pty_slave(self):
        """Child stdin must be connected to a PTY slave device."""
        d = self._get_report()
        tty = d.get('STDIN_TTY', 'none')
        assert tty.startswith('/dev/pts/'), (
            f"STDIN_TTY={tty}, expected a /dev/pts/* device"
        )

    def test_foreground_process_group(self):
        """Terminal foreground process group must equal the child PGID."""
        d = self._get_report()
        fgpg = d.get('FGPG', '-1')
        pgid = d.get('PGID', '-2')
        assert fgpg == pgid, (
            f"FGPG={fgpg} != PGID={pgid}"
        )

    def test_no_leaked_file_descriptors(self):
        """Child must have exactly 3 open FDs (stdin, stdout, stderr)."""
        d = self._get_report()
        assert d['FD_COUNT'] == '3', (
            f"FD_COUNT={d['FD_COUNT']}, expected 3"
        )

    def test_window_size(self):
        """PTY must have dimensions at least 24 rows x 80 columns."""
        d = self._get_report()
        rows = int(d.get('ROWS', '0'))
        cols = int(d.get('COLS', '0'))
        assert rows >= 24, f"ROWS={rows}, expected >= 24"
        assert cols >= 80, f"COLS={cols}, expected >= 80"

    # --- Exit code propagation ---

    def test_exit_code_success(self):
        """Exit code 0 from child must propagate."""
        try:
            r = run_session(["/bin/true"], timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("ptysession hung running /bin/true")
        assert r.returncode == 0

    def test_exit_code_failure(self):
        """Non-zero exit code from child must propagate."""
        try:
            r = run_session(["/bin/sh", "-c", "exit 42"], timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("ptysession hung running exit 42")
        assert r.returncode == 42, (
            f"Expected exit code 42, got {r.returncode}"
        )

    # --- I/O relay ---

    def test_stdout_relay(self):
        """Child stdout must be relayed through the PTY to ptysession stdout."""
        try:
            r = run_session(
                ["/bin/sh", "-c", "echo RELAY_MARKER_7f3a"],
                timeout=10
            )
        except subprocess.TimeoutExpired:
            pytest.fail("ptysession hung during output relay test")
        out = r.stdout.replace('\r', '')
        assert 'RELAY_MARKER_7f3a' in out, (
            f"Marker not found in output: {r.stdout!r}"
        )

    def test_multiline_output(self):
        """Multiple output lines must all be relayed."""
        try:
            r = run_session(
                ["/bin/sh", "-c",
                 "echo ALPHA_1 && echo BETA_2 && echo GAMMA_3"],
                timeout=10
            )
        except subprocess.TimeoutExpired:
            pytest.fail("ptysession hung during multiline test")
        out = r.stdout.replace('\r', '')
        for marker in ['ALPHA_1', 'BETA_2', 'GAMMA_3']:
            assert marker in out, f"Missing {marker} in output"

    # --- Signal forwarding ---

    def test_sigterm_forwarding(self):
        """SIGTERM sent to ptysession must be forwarded to child process group."""
        proc = subprocess.Popen(
            [PTYSESSION, "/bin/sleep", "300"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(0.5)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("ptysession did not exit after SIGTERM")
        # Child killed by SIGTERM -> exit code 128+15=143
        assert proc.returncode == 143, (
            f"Expected exit code 143 (128+SIGTERM), got {proc.returncode}"
        )

    def test_sigint_forwarding(self):
        """SIGINT sent to ptysession must be forwarded to child process group."""
        proc = subprocess.Popen(
            [PTYSESSION, "/bin/sleep", "300"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(0.5)
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("ptysession did not exit after SIGINT")
        # Child killed by SIGINT -> exit code 128+2=130
        assert proc.returncode == 130, (
            f"Expected exit code 130 (128+SIGINT), got {proc.returncode}"
        )

    # --- Stdin forwarding ---

    def test_stdin_forwarding(self):
        """Data on ptysession's stdin (pipe) must be forwarded through PTY."""
        proc = subprocess.Popen(
            [PTYSESSION, "/bin/sh", "-c",
             "read line && echo ECHO:$line"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            stdout, _ = proc.communicate(
                input=b"fwd_test_4c7e\n", timeout=10
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("ptysession hung during stdin forwarding")
        out = stdout.replace(b'\r', b'').decode(errors='replace')
        assert 'ECHO:fwd_test_4c7e' in out, (
            f"Forwarded data not found in output: {out!r}"
        )
