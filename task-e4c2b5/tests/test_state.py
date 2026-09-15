
import subprocess
import os
import pytest

INCLUDE = "/app/include"
TESTS_DIR = "/tests"
TMP = "/tmp/bbuf_tests"


def _compile(src, output, extra_flags=None):
    """Compile a C++ test source against the implementation."""
    flags = [
        "g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
        f"-I{INCLUDE}", src, "-o", output, "-lpthread"
    ]
    if extra_flags:
        flags = flags[:3] + extra_flags + flags[3:]
    r = subprocess.run(flags, capture_output=True, text=True, timeout=60)
    return r


def _run(binary, timeout=120):
    """Run a compiled test binary."""
    env = os.environ.copy()
    env["TSAN_OPTIONS"] = "halt_on_error=1"
    r = subprocess.run(
        [binary], capture_output=True, text=True, timeout=timeout, env=env
    )
    return r


@pytest.fixture(scope="session", autouse=True)
def build_dir():
    os.makedirs(TMP, exist_ok=True)


def test_compilation():
    """The implementation must compile without errors."""
    r = _compile(
        f"{TESTS_DIR}/test_basic.cpp",
        f"{TMP}/test_basic"
    )
    assert r.returncode == 0, (
        f"Compilation failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_basic_correctness():
    """Single-threaded basic correctness tests."""
    _compile(f"{TESTS_DIR}/test_basic.cpp", f"{TMP}/test_basic")
    r = _run(f"{TMP}/test_basic", timeout=30)
    assert r.returncode == 0, (
        f"Basic tests failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "All basic tests passed" in r.stdout, (
        f"Not all basic tests passed:\n{r.stdout}"
    )


def test_stress_correctness():
    """Multi-threaded stress test with data integrity verification."""
    rc = _compile(f"{TESTS_DIR}/test_stress.cpp", f"{TMP}/test_stress")
    assert rc.returncode == 0, f"Stress test compile failed:\n{rc.stderr}"
    r = _run(f"{TMP}/test_stress", timeout=60)
    assert r.returncode == 0, (
        f"Stress test failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "PASS" in r.stdout, f"Stress test did not pass:\n{r.stdout}"


def test_framing_correctness():
    """Zero-copy message framing test with header/payload verification."""
    rc = _compile(f"{TESTS_DIR}/test_framing.cpp", f"{TMP}/test_framing")
    assert rc.returncode == 0, f"Framing test compile failed:\n{rc.stderr}"
    r = _run(f"{TMP}/test_framing", timeout=60)
    assert r.returncode == 0, (
        f"Framing test failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "PASS" in r.stdout, f"Framing test did not pass:\n{r.stdout}"


def test_thread_sanitizer():
    """Implementation must be ThreadSanitizer clean."""
    tsan_flags = ["-g", "-O1", "-fsanitize=thread"]
    rc = _compile(
        f"{TESTS_DIR}/test_stress.cpp",
        f"{TMP}/test_stress_tsan",
        extra_flags=tsan_flags,
    )
    assert rc.returncode == 0, f"TSan compile failed:\n{rc.stderr}"
    r = _run(f"{TMP}/test_stress_tsan", timeout=180)
    assert r.returncode == 0, (
        f"ThreadSanitizer detected issues:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "PASS" in r.stdout, (
        f"Stress test under TSan did not pass:\n{r.stdout}\n{r.stderr}"
    )
