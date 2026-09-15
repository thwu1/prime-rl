
import subprocess
import os
import pytest


@pytest.fixture(scope="session")
def build_and_run():
    """Compile the test harness against the agent's implementation and run it."""
    assert os.path.exists("/app/walloc_native.c"), \
        "walloc_native.c not found at /app/"
    assert os.path.exists("/app/walloc_native.h"), \
        "walloc_native.h not found at /app/"

    compile_result = subprocess.run(
        ["gcc", "-O2", "-Wall", "-Wno-unused-function",
         "-o", "/app/test_harness",
         "/tests/test_harness.c", "/app/walloc_native.c",
         "-I/app/"],
        capture_output=True, text=True
    )
    assert compile_result.returncode == 0, \
        f"Compilation failed:\n{compile_result.stderr}"

    run_result = subprocess.run(
        ["/app/test_harness"],
        capture_output=True, text=True,
        timeout=60
    )
    return run_result


def test_compiles(build_and_run):
    """Implementation compiles without errors."""
    pass


def test_basic_malloc(build_and_run):
    assert "PASS: basic_malloc" in build_and_run.stdout, \
        f"basic_malloc failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_usable_size_small(build_and_run):
    assert "PASS: usable_size_small" in build_and_run.stdout, \
        f"usable_size_small failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_usable_size_large(build_and_run):
    assert "PASS: usable_size_large" in build_and_run.stdout, \
        f"usable_size_large failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_usable_size_null(build_and_run):
    assert "PASS: usable_size_null" in build_and_run.stdout, \
        f"usable_size_null failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_null(build_and_run):
    assert "PASS: realloc_null" in build_and_run.stdout, \
        f"realloc_null failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_zero(build_and_run):
    assert "PASS: realloc_zero" in build_and_run.stdout, \
        f"realloc_zero failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_grow(build_and_run):
    assert "PASS: realloc_grow" in build_and_run.stdout, \
        f"realloc_grow failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_shrink(build_and_run):
    assert "PASS: realloc_shrink" in build_and_run.stdout, \
        f"realloc_shrink failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_same_class(build_and_run):
    assert "PASS: realloc_same_class" in build_and_run.stdout, \
        f"realloc_same_class failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_small_to_large(build_and_run):
    assert "PASS: realloc_small_to_large" in build_and_run.stdout, \
        f"realloc_small_to_large failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_large_to_small(build_and_run):
    assert "PASS: realloc_large_to_small" in build_and_run.stdout, \
        f"realloc_large_to_small failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_realloc_grow_large(build_and_run):
    assert "PASS: realloc_grow_large" in build_and_run.stdout, \
        f"realloc_grow_large failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_stress(build_and_run):
    assert "PASS: stress" in build_and_run.stdout, \
        f"stress test failed:\n{build_and_run.stdout}\n{build_and_run.stderr}"


def test_all_pass(build_and_run):
    assert "All tests PASSED" in build_and_run.stdout, \
        f"Not all tests passed:\n{build_and_run.stdout}\n{build_and_run.stderr}"
    assert build_and_run.returncode == 0, \
        f"Test harness exited with code {build_and_run.returncode}"
