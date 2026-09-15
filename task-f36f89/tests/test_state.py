"""
Tests for the ARM Cortex-M3 preemptive threading kernel.
"""
import subprocess
import os
import pytest

QEMU_TIMEOUT = 45  # seconds to run QEMU


@pytest.fixture(scope="session")
def build():
    """Build the kernel."""
    subprocess.run(["make", "-C", "/app", "clean"],
                   capture_output=True, timeout=30)
    result = subprocess.run(["make", "-C", "/app"],
                            capture_output=True, timeout=60)
    assert result.returncode == 0, \
        f"Build failed:\n{result.stderr.decode(errors='replace')}"
    assert os.path.exists("/app/os.bin"), "os.bin not produced"
    return True


@pytest.fixture(scope="session")
def qemu_output(build):
    """Run the kernel in QEMU and capture UART output."""
    result = subprocess.run(
        ["timeout", str(QEMU_TIMEOUT),
         "qemu-system-arm", "-M", "mps2-an385",
         "-nographic", "-kernel", "/app/os.bin"],
        capture_output=True,
        timeout=QEMU_TIMEOUT + 15,
    )
    output = result.stdout.decode(errors="replace")
    assert len(output) > 0, \
        f"No QEMU output. stderr: {result.stderr.decode(errors='replace')[:500]}"
    return output


# ---- Build -----------------------------------------------------------

class TestBuild:
    def test_binary_produced(self, build):
        """Build produces a non-trivial os.bin."""
        assert os.path.exists("/app/os.bin")
        assert os.path.getsize("/app/os.bin") > 100


# ---- Boot -------------------------------------------------------------

class TestBoot:
    def test_boot_message(self, qemu_output):
        """Kernel boots and prints the BOOT marker."""
        assert "BOOT" in qemu_output, \
            f"No BOOT message. First 300 chars:\n{qemu_output[:300]}"


# ---- Thread creation --------------------------------------------------

class TestThreadCreation:
    def test_w1_runs(self, qemu_output):
        assert "W1: running" in qemu_output

    def test_w2_runs(self, qemu_output):
        assert "W2: running" in qemu_output

    def test_w3_runs(self, qemu_output):
        assert "W3: running" in qemu_output

    def test_sentinel_runs(self, qemu_output):
        assert "sentinel: alive" in qemu_output

    def test_all_four_threads(self, qemu_output):
        """All four threads produce output."""
        expected = ["W1: running", "W2: running",
                    "W3: running", "sentinel: alive"]
        missing = [t for t in expected if t not in qemu_output]
        assert not missing, f"Missing thread output: {missing}"


# ---- Preemptive scheduling -------------------------------------------

class TestPreemption:
    def test_output_interleaved(self, qemu_output):
        """Output from different threads must be interleaved,
        proving the scheduler preempts rather than running
        cooperatively."""
        lines = [l.strip() for l in qemu_output.split("\n") if l.strip()]

        seq = []
        for line in lines:
            if "W1:" in line:
                seq.append("W1")
            elif "W2:" in line:
                seq.append("W2")
            elif "W3:" in line:
                seq.append("W3")
            elif "sentinel:" in line:
                seq.append("S")

        assert len(seq) >= 8, \
            f"Too few thread lines ({len(seq)})"

        transitions = sum(1 for i in range(1, len(seq))
                          if seq[i] != seq[i - 1])
        assert transitions >= 3, \
            f"Only {transitions} thread transitions — output not interleaved. " \
            f"Sequence (first 30): {seq[:30]}"

    def test_at_least_three_distinct(self, qemu_output):
        """At least three distinct threads must appear."""
        seen = set()
        for line in qemu_output.split("\n"):
            if "W1:" in line:
                seen.add("W1")
            elif "W2:" in line:
                seen.add("W2")
            elif "W3:" in line:
                seen.add("W3")
            elif "sentinel:" in line:
                seen.add("S")
        assert len(seen) >= 3, \
            f"Only {len(seen)} distinct threads produced output: {seen}"


# ---- Thread termination ----------------------------------------------

class TestTermination:
    def test_workers_bounded(self, qemu_output):
        """Each worker prints at most ~5 times (small tolerance)."""
        w1 = qemu_output.count("W1: running")
        w2 = qemu_output.count("W2: running")
        w3 = qemu_output.count("W3: running")
        assert 1 <= w1 <= 8, f"W1 count {w1} out of range"
        assert 1 <= w2 <= 8, f"W2 count {w2} out of range"
        assert 1 <= w3 <= 8, f"W3 count {w3} out of range"

    def test_sentinel_outlasts_workers(self, qemu_output):
        """Sentinel must produce significantly more lines than any worker.
        Workers run 5 iterations then terminate; sentinel runs indefinitely."""
        s = qemu_output.count("sentinel: alive")
        mx = max(qemu_output.count("W1: running"),
                 qemu_output.count("W2: running"),
                 qemu_output.count("W3: running"))
        assert s > mx, \
            f"Sentinel ({s}) should outlast each worker (max {mx})"

    def test_system_stable_after_exit(self, qemu_output):
        """Sentinel output must appear after the last worker output,
        proving the system did not crash when workers terminated."""
        lines = qemu_output.split("\n")
        last_sentinel = -1
        last_worker = -1
        for i, line in enumerate(lines):
            if "sentinel:" in line:
                last_sentinel = i
            if any(f"W{j}:" in line for j in (1, 2, 3)):
                last_worker = i
        if last_worker >= 0 and last_sentinel >= 0:
            assert last_sentinel > last_worker, \
                "Sentinel stopped before workers — system may have crashed"


# ---- Integrity --------------------------------------------------------

class TestIntegrity:
    def test_os_c_unmodified(self):
        """os.c must not have its API calls altered."""
        with open("/app/os.c", "rb") as f:
            data = f.read()
        assert b'thread_create(worker, "W1")' in data
        assert b'thread_create(worker, "W2")' in data
        assert b'thread_create(worker, "W3")' in data
        assert b"thread_create(sentinel" in data
        assert b"thread_start()" in data
