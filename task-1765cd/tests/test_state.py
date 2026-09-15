import subprocess
import os
import re
import pytest



def read_source():
    with open("/app/include/spsc_queue.hpp") as f:
        return f.read()


def strip_comments(code):
    """Remove C and C++ comments from source code."""
    code = re.sub(r'//.*', '', code)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    return code


class TestSourceCode:
    """Static analysis of the lock-free implementation."""

    def test_no_mutex(self):
        """Implementation must not use mutex for synchronization."""
        code = strip_comments(read_source())
        assert "mutex" not in code.lower(), \
            "Lock-free implementation must not use std::mutex"

    def test_uses_atomic(self):
        """Implementation must use std::atomic."""
        code = read_source()
        assert "atomic" in code, \
            "Implementation must use std::atomic for lock-free operation"

    def test_memory_ordering_acquire(self):
        """Must use acquire ordering for cross-thread loads."""
        code = read_source()
        has_acquire = ("memory_order_acquire" in code or
                       "memory_order::acquire" in code)
        assert has_acquire, \
            "Implementation must use memory_order_acquire for cross-thread loads"

    def test_memory_ordering_release(self):
        """Must use release ordering for cross-thread stores."""
        code = read_source()
        has_release = ("memory_order_release" in code or
                       "memory_order::release" in code)
        assert has_release, \
            "Implementation must use memory_order_release for cross-thread stores"

    def test_no_all_seq_cst(self):
        """Should not use sequential consistency for all operations."""
        code = strip_comments(read_source())
        seq_cst_count = (code.count("memory_order_seq_cst") +
                         code.count("memory_order::seq_cst"))
        acq_rel_count = (code.count("memory_order_acquire") +
                         code.count("memory_order::acquire") +
                         code.count("memory_order_release") +
                         code.count("memory_order::release"))
        assert acq_rel_count > seq_cst_count, \
            ("Implementation should primarily use acquire/release ordering, "
             "not sequential consistency everywhere")

    def test_false_sharing_prevention(self):
        """Head and tail must be on separate cache lines."""
        code = read_source()
        has_alignment = any(pattern in code for pattern in [
            "alignas(64)", "alignas(128)", "alignas( 64)", "alignas( 128)",
            "hardware_destructive_interference_size",
            "__attribute__((aligned",
        ])
        # Also check for manual padding between head and tail
        has_padding = bool(re.search(
            r'(char|uint8_t|std::byte)\s+pad', code))
        assert has_alignment or has_padding, \
            ("Implementation must prevent false sharing between head and tail "
             "(use alignas(64) or padding for cache line separation)")


class TestCompilation:
    """Build tests."""

    def test_compiles_clean(self):
        """Must compile without errors."""
        subprocess.run(["make", "clean"], cwd="/app",
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ["make", "stress_test"], cwd="/app",
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, \
            f"Compilation failed:\n{result.stderr}"

    def test_compiles_with_tsan(self):
        """Must compile with ThreadSanitizer."""
        result = subprocess.run(
            ["make", "stress_test_tsan"], cwd="/app",
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, \
            f"TSan compilation failed:\n{result.stderr}"

    def test_compiles_benchmark(self):
        """Benchmark must compile."""
        result = subprocess.run(
            ["make", "benchmark"], cwd="/app",
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, \
            f"Benchmark compilation failed:\n{result.stderr}"


class TestCorrectness:
    """Runtime correctness tests."""

    def test_basic_single_thread(self):
        """Basic single-threaded push/pop correctness."""
        test_source = r'''
#include "spsc_queue.hpp"
#include <cassert>
#include <iostream>

int main() {
    SPSCQueue<int> q(4);

    // Fill queue
    assert(q.push(10));
    assert(q.push(20));
    assert(q.push(30));
    assert(q.push(40));
    assert(!q.push(50));  // full

    // Drain partially
    int val = 0;
    assert(q.consume_one([&](int v) { val = v; }));
    assert(val == 10);
    assert(q.consume_one([&](int v) { val = v; }));
    assert(val == 20);

    // Refill
    assert(q.push(50));
    assert(q.push(60));
    assert(!q.push(70));  // full again

    // Drain all
    assert(q.consume_one([&](int v) { val = v; }));
    assert(val == 30);
    assert(q.consume_one([&](int v) { val = v; }));
    assert(val == 40);
    assert(q.consume_one([&](int v) { val = v; }));
    assert(val == 50);
    assert(q.consume_one([&](int v) { val = v; }));
    assert(val == 60);
    assert(!q.consume_one([&](int v) { val = v; }));  // empty

    // Capacity check
    assert(q.capacity() == 4);

    std::cout << "BASIC_TEST_PASSED" << std::endl;
    return 0;
}
'''
        with open("/tmp/basic_test.cpp", "w") as f:
            f.write(test_source)

        result = subprocess.run(
            ["g++", "-std=c++20", "-O2", "-I", "/app/include",
             "-o", "/tmp/basic_test", "/tmp/basic_test.cpp", "-pthread"],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, \
            f"Basic test compilation failed:\n{result.stderr}"

        result = subprocess.run(
            ["/tmp/basic_test"],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, \
            f"Basic test failed:\n{result.stdout}\n{result.stderr}"
        assert "BASIC_TEST_PASSED" in result.stdout

    def test_stress_sequential_values(self):
        """All values must arrive in order under concurrent stress."""
        build = subprocess.run(
            ["make", "stress_test"], cwd="/app",
            capture_output=True, text=True, timeout=60)
        assert build.returncode == 0, \
            f"Stress test build failed:\n{build.stderr}"

        result = subprocess.run(
            ["/app/build/stress_test", "5000000"],
            capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, \
            f"Stress test crashed:\n{result.stdout}\n{result.stderr}"
        assert "STRESS_TEST_PASSED" in result.stdout, \
            f"Stress test did not pass:\n{result.stdout}"

    def test_tsan_clean(self):
        """ThreadSanitizer must report no data races."""
        build = subprocess.run(
            ["make", "stress_test_tsan"], cwd="/app",
            capture_output=True, text=True, timeout=60)
        assert build.returncode == 0, \
            f"TSan build failed:\n{build.stderr}"

        env = {**os.environ, "TSAN_OPTIONS": "halt_on_error=1"}
        result = subprocess.run(
            ["/app/build/stress_test_tsan", "500000"],
            capture_output=True, text=True, timeout=180, env=env)
        tsan_error = ("ThreadSanitizer" in result.stderr and
                      ("data race" in result.stderr or
                       "WARNING" in result.stderr))
        assert not tsan_error, \
            f"ThreadSanitizer detected data races:\n{result.stderr}"
        assert result.returncode == 0, \
            (f"Stress test with TSan failed "
             f"(exit {result.returncode}):\n{result.stderr}")


class TestPerformance:
    """Throughput benchmarks."""

    def test_throughput_vs_mutex(self):
        """Lock-free must achieve >= 2x throughput over mutex baseline."""
        build = subprocess.run(
            ["make", "benchmark"], cwd="/app",
            capture_output=True, text=True, timeout=60)
        assert build.returncode == 0, \
            f"Benchmark build failed:\n{build.stderr}"

        result = subprocess.run(
            ["/app/build/benchmark"],
            capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, \
            f"Benchmark failed:\n{result.stdout}\n{result.stderr}"

        lockfree_ops = None
        mutex_ops = None
        for line in result.stdout.strip().split('\n'):
            if line.startswith("LOCKFREE_BEST:"):
                lockfree_ops = float(line.split(":")[1].strip())
            elif line.startswith("MUTEX_BEST:"):
                mutex_ops = float(line.split(":")[1].strip())

        assert lockfree_ops is not None, \
            f"Could not parse lockfree throughput:\n{result.stdout}"
        assert mutex_ops is not None, \
            f"Could not parse mutex throughput:\n{result.stdout}"
        assert mutex_ops > 0, "Mutex throughput must be positive"

        ratio = lockfree_ops / mutex_ops
        assert ratio >= 2.0, \
            (f"Lock-free ({lockfree_ops:.0f} ops/s) must be >= 2x faster "
             f"than mutex ({mutex_ops:.0f} ops/s), got {ratio:.2f}x")
