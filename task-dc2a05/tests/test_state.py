"""
Tests for the lock-free concurrent hash map implementation.

"""
import subprocess
import os
import pytest

BUILD_DIR = "/tmp/hashmap_tests"
IMPL_FILE = "/app/src/concurrent_hashmap.cpp"
OBJ_FILE = os.path.join(BUILD_DIR, "concurrent_hashmap.o")

BASE_FLAGS = ["-std=c++17", "-pthread", "-O2", "-I/app/include"]


@pytest.fixture(scope="session", autouse=True)
def compile_implementation():
    """Compile the implementation into an object file before all tests."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    assert os.path.exists(IMPL_FILE), (
        f"Implementation file not found at {IMPL_FILE}. "
        "You must create /app/src/concurrent_hashmap.cpp."
    )
    result = subprocess.run(
        ["g++"] + BASE_FLAGS + ["-c", IMPL_FILE, "-o", OBJ_FILE],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"Implementation compilation failed:\n{result.stderr}"


def _compile_and_run(test_cpp, binary_name, timeout=120):
    """Compile a test source file, link with implementation, and run."""
    binary = os.path.join(BUILD_DIR, binary_name)
    r = subprocess.run(
        ["g++"] + BASE_FLAGS + [f"/tests/{test_cpp}", OBJ_FILE, "-o", binary],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"Test compilation of {test_cpp} failed:\n{r.stderr}"
    r = subprocess.run([binary], capture_output=True, text=True, timeout=timeout)
    return r


def test_basic_operations():
    """Single-threaded insert, update, get, erase, and re-insert."""
    r = _compile_and_run("test_basic.cpp", "test_basic")
    assert r.returncode == 0, (
        f"Basic test failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
    )
    assert "PASS" in r.stdout, f"Basic test did not print PASS:\n{r.stdout}"


def test_concurrent_operations():
    """Multi-threaded inserts with disjoint and overlapping key ranges."""
    r = _compile_and_run("test_concurrent.cpp", "test_concurrent", timeout=120)
    assert r.returncode == 0, (
        f"Concurrent test failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
    )
    assert "PASS" in r.stdout, f"Concurrent test did not print PASS:\n{r.stdout}"


def test_migration():
    """Table migration under single-threaded and multi-threaded insertion."""
    r = _compile_and_run("test_migration.cpp", "test_migration", timeout=120)
    assert r.returncode == 0, (
        f"Migration test failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
    )
    assert "PASS" in r.stdout, f"Migration test did not print PASS:\n{r.stdout}"


def test_thread_sanitizer():
    """Compile with ThreadSanitizer and run concurrent tests for race detection."""
    tsan_flags = ["-std=c++17", "-pthread", "-O1", "-g", "-fsanitize=thread",
                  "-I/app/include"]
    tsan_obj = os.path.join(BUILD_DIR, "impl_tsan.o")

    # Compile implementation with TSan
    r = subprocess.run(
        ["g++"] + tsan_flags + ["-c", IMPL_FILE, "-o", tsan_obj],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        pytest.skip(f"ThreadSanitizer compilation not available: {r.stderr[:200]}")

    # Compile test with TSan
    tsan_binary = os.path.join(BUILD_DIR, "test_tsan")
    r = subprocess.run(
        ["g++"] + tsan_flags + ["/tests/test_concurrent.cpp", tsan_obj,
                                "-o", tsan_binary],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"TSan test compilation failed:\n{r.stderr}"

    # Run with TSan
    env = os.environ.copy()
    env["TSAN_OPTIONS"] = "halt_on_error=1"
    r = subprocess.run(
        [tsan_binary], capture_output=True, text=True, timeout=180, env=env,
    )
    assert "ThreadSanitizer" not in r.stderr, (
        f"ThreadSanitizer detected a data race:\n{r.stderr}"
    )
    assert r.returncode == 0, (
        f"TSan test failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
    )
