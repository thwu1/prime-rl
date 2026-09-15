# test_state.py - Pytest verification for PEP 703 Biased Reference Counting
#

import subprocess
import pytest
import os

BINARY_PATH = "/tmp/test_brc"


@pytest.fixture(scope="session", autouse=True)
def compiled_binary():
    """Compile the BRC implementation against the test harness once per session."""
    result = subprocess.run(
        [
            "gcc", "-D_GNU_SOURCE",
            "-Wall", "-Wextra", "-std=gnu11", "-O2", "-pthread",
            "-I", "/app/include",
            "-o", BINARY_PATH,
            "/tests/test_brc.c", "/app/src/brc.c",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Compilation failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    os.chmod(BINARY_PATH, 0o755)
    return BINARY_PATH


def _run_test(name, timeout=30):
    result = subprocess.run(
        [BINARY_PATH, name],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"Test '{name}' failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_alloc_basic(compiled_binary):
    _run_test("alloc_basic")


def test_incref_decref_owner(compiled_binary):
    _run_test("incref_decref_owner")


def test_immortal(compiled_binary):
    _run_test("immortal")


def test_try_incref_live(compiled_binary):
    _run_test("try_incref_live")


def test_shared_incref(compiled_binary):
    _run_test("shared_incref")


def test_merge_state(compiled_binary):
    _run_test("merge_state")


def test_dealloc_merged(compiled_binary):
    _run_test("dealloc_merged")


def test_concurrent_shared(compiled_binary):
    _run_test("concurrent_shared", timeout=120)


def test_concurrent_balanced(compiled_binary):
    _run_test("concurrent_balanced", timeout=120)


def test_full_lifecycle(compiled_binary):
    _run_test("full_lifecycle")
