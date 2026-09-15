
import subprocess
import os

def run_cmd(cmd, timeout=60, cwd="/app"):
    """Run a shell command and return the result."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        timeout=timeout, cwd=cwd
    )


class TestHashmapRehashCycle:
    """Tests for the hash table concurrent rehash cycle bug task."""

    def test_01_build_stress_test(self):
        """stress_test must compile successfully."""
        r = run_cmd("make clean && make stress_test")
        assert r.returncode == 0, (
            f"stress_test build failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_02_build_simulate(self):
        """simulate must compile successfully."""
        r = run_cmd("make simulate")
        assert r.returncode == 0, (
            f"simulate build failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_03_build_detect_cycle(self):
        """detect_cycle must compile successfully."""
        r = run_cmd("make detect_cycle")
        assert r.returncode == 0, (
            f"detect_cycle build failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_04_simulate_identifies_cycle_bucket(self):
        """Simulation must identify the correct cycle bucket."""
        run_cmd("make simulate")
        r = run_cmd("./simulate", timeout=15)
        assert r.returncode == 0, f"simulate crashed: {r.stderr}"
        assert "CYCLE_BUCKET=3" in r.stdout, (
            f"Expected CYCLE_BUCKET=3 in output:\n{r.stdout}"
        )

    def test_05_simulate_identifies_cycle_entries(self):
        """Simulation must identify the correct entries involved in the cycle."""
        run_cmd("make simulate")
        r = run_cmd("./simulate", timeout=15)
        assert r.returncode == 0, f"simulate crashed: {r.stderr}"
        has_entries = (
            "CYCLE_ENTRIES=alpha,bravo" in r.stdout
            or "CYCLE_ENTRIES=bravo,alpha" in r.stdout
        )
        assert has_entries, (
            f"Expected CYCLE_ENTRIES=alpha,bravo or bravo,alpha in output:\n{r.stdout}"
        )

    def test_06_detect_cycle_finds_cycle(self):
        """Cycle detection must correctly identify a cyclic linked list."""
        run_cmd("make detect_cycle")
        r = run_cmd("./detect_cycle", timeout=15)
        assert r.returncode == 0, f"detect_cycle crashed: {r.stderr}"
        assert "CYCLE_FOUND" in r.stdout, (
            f"Expected CYCLE_FOUND in output:\n{r.stdout}"
        )

    def test_07_detect_cycle_no_false_positive(self):
        """Cycle detection must not report false positives on normal lists."""
        run_cmd("make detect_cycle")
        r = run_cmd("./detect_cycle", timeout=15)
        assert r.returncode == 0, f"detect_cycle crashed: {r.stderr}"
        assert "NO_CYCLE" in r.stdout, (
            f"Expected NO_CYCLE in output:\n{r.stdout}"
        )

    def test_08_stress_test_no_hang(self):
        """Fixed hash table must not hang under concurrent load."""
        run_cmd("make clean && make stress_test")
        r = run_cmd("./stress_test", timeout=120)
        assert r.returncode == 0, (
            f"stress_test failed or timed out:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
        assert "PASS" in r.stdout, (
            f"stress_test did not report PASS:\n{r.stdout}"
        )

    def test_09_answer_file_exists(self):
        """answer.txt must exist with correct cycle information."""
        assert os.path.exists("/app/answer.txt"), "answer.txt not found at /app/answer.txt"
        with open("/app/answer.txt") as f:
            content = f.read()
        assert "CYCLE_BUCKET=3" in content, (
            f"answer.txt missing CYCLE_BUCKET=3:\n{content}"
        )
        has_entries = (
            "CYCLE_ENTRIES=alpha,bravo" in content
            or "CYCLE_ENTRIES=bravo,alpha" in content
        )
        assert has_entries, (
            f"answer.txt missing correct CYCLE_ENTRIES:\n{content}"
        )

    def test_10_hashtable_has_synchronization(self):
        """Fixed hashtable.c must use thread synchronization primitives."""
        with open("/app/hashtable.c") as f:
            code = f.read()
        sync_primitives = [
            "pthread_rwlock", "pthread_mutex", "_Atomic", "atomic_",
            "sem_wait", "pthread_spin",
        ]
        has_sync = any(p in code for p in sync_primitives)
        assert has_sync, (
            "hashtable.c must include thread synchronization primitives "
            "(pthread_rwlock, pthread_mutex, atomics, etc.)"
        )
