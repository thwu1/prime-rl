
"""Tests for the SPSC queue fix and batch queue implementation."""

import subprocess
import pytest


def compile_test(src, output, extra_flags=None):
    """Compile a C++ test file against /app/include headers."""
    flags = [
        "g++", "-std=c++20", "-O2", "-Wall", "-Wextra", "-pthread",
        "-I/app/include",
        src, "-o", output,
    ]
    if extra_flags:
        flags.extend(extra_flags)
    result = subprocess.run(flags, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"Compilation of {src} failed:\n{result.stderr}"


def run_binary(binary, timeout=60):
    """Run a compiled test binary and return the result."""
    return subprocess.run([binary], capture_output=True, text=True, timeout=timeout)


# === SPSC Queue Tests ===


class TestCapacity:
    """Queue of capacity N must hold exactly N items."""

    def test_capacity(self):
        compile_test("/tests/test_capacity.cpp", "/tmp/test_capacity")
        result = run_binary("/tmp/test_capacity", timeout=30)
        assert result.returncode == 0, (
            f"Capacity test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestConcurrentCorrectness:
    """Items must arrive in FIFO order under concurrent producer/consumer."""

    def test_concurrent(self):
        compile_test("/tests/test_concurrent.cpp", "/tmp/test_concurrent")
        result = run_binary("/tmp/test_concurrent", timeout=120)
        assert result.returncode == 0, (
            f"Concurrent test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestThreadSanitizer:
    """No data races detected by ThreadSanitizer."""

    def test_tsan(self):
        compile_test(
            "/tests/test_concurrent.cpp", "/tmp/test_tsan",
            extra_flags=["-fsanitize=thread", "-g", "-O1"],
        )
        result = run_binary("/tmp/test_tsan", timeout=180)
        has_race = "ThreadSanitizer" in result.stderr
        assert not has_race, (
            f"ThreadSanitizer detected data races:\n{result.stderr[:3000]}"
        )
        assert result.returncode == 0, (
            f"TSan test exited with code {result.returncode}:\n{result.stderr[:2000]}"
        )


class TestCacheLineSeparation:
    """head and tail atomics must reside on separate cache lines."""

    def test_cacheline(self):
        compile_test("/tests/test_cacheline.cpp", "/tmp/test_cacheline")
        result = run_binary("/tmp/test_cacheline", timeout=30)
        assert result.returncode == 0, (
            f"Cache line test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestLockFree:
    """Implementation must not use mutexes or blocking synchronization."""

    def test_no_mutex(self):
        with open("/app/include/spsc_queue.hpp") as f:
            content = f.read()
        for pattern in ["#include <mutex>", "std::mutex", "std::lock_guard",
                        "std::unique_lock", "std::condition_variable"]:
            assert pattern not in content, (
                f"Lock-free queue must not use {pattern}"
            )


class TestNonDefaultConstructible:
    """Queue must work with types that have no default constructor."""

    def test_ndc(self):
        compile_test("/tests/test_ndc.cpp", "/tmp/test_ndc")
        result = run_binary("/tmp/test_ndc", timeout=30)
        assert result.returncode == 0, (
            f"NDC test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


# === Batch Queue Tests ===


class TestBatchCapacity:
    """Batch queue capacity and atomic push_batch semantics."""

    def test_batch_capacity(self):
        compile_test("/tests/test_batch_capacity.cpp", "/tmp/test_batch_capacity")
        result = run_binary("/tmp/test_batch_capacity", timeout=30)
        assert result.returncode == 0, (
            f"Batch capacity test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestBatchConcurrent:
    """Concurrent batch producer/consumer preserves FIFO ordering."""

    def test_batch_concurrent(self):
        compile_test("/tests/test_batch_concurrent.cpp", "/tmp/test_batch_concurrent")
        result = run_binary("/tmp/test_batch_concurrent", timeout=120)
        assert result.returncode == 0, (
            f"Batch concurrent test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestBatchConsume:
    """consume_batch partial drain and edge case behavior."""

    def test_batch_consume(self):
        compile_test("/tests/test_batch_consume.cpp", "/tmp/test_batch_consume")
        result = run_binary("/tmp/test_batch_consume", timeout=30)
        assert result.returncode == 0, (
            f"Batch consume test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestBatchThreadSanitizer:
    """No data races in batch queue under ThreadSanitizer."""

    def test_batch_tsan(self):
        compile_test(
            "/tests/test_batch_concurrent.cpp", "/tmp/test_batch_tsan",
            extra_flags=["-fsanitize=thread", "-g", "-O1"],
        )
        result = run_binary("/tmp/test_batch_tsan", timeout=180)
        has_race = "ThreadSanitizer" in result.stderr
        assert not has_race, (
            f"ThreadSanitizer detected data races in batch queue:\n{result.stderr[:3000]}"
        )
        assert result.returncode == 0, (
            f"Batch TSan test exited with code {result.returncode}:\n{result.stderr[:2000]}"
        )


class TestBatchCacheLine:
    """Batch queue head/tail must be on separate cache lines."""

    def test_batch_cacheline(self):
        compile_test("/tests/test_batch_cacheline.cpp", "/tmp/test_batch_cacheline")
        result = run_binary("/tmp/test_batch_cacheline", timeout=30)
        assert result.returncode == 0, (
            f"Batch cache line test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout


class TestBatchLockFree:
    """Batch queue must not use mutexes or blocking synchronization."""

    def test_batch_no_mutex(self):
        with open("/app/include/spsc_batch_queue.hpp") as f:
            content = f.read()
        for pattern in ["#include <mutex>", "std::mutex", "std::lock_guard",
                        "std::unique_lock", "std::condition_variable"]:
            assert pattern not in content, (
                f"Batch queue must not use {pattern}"
            )
