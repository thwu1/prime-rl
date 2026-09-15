
import subprocess
import pytest
import os

COMPILE_FLAGS = ["-std=c++17", "-O2", "-pthread", "-I/app"]


def compile_and_run(test_name, timeout=120):
    src = f"/tests/{test_name}.cpp"
    binary = f"/tmp/{test_name}"

    # Compile
    comp = subprocess.run(
        ["g++"] + COMPILE_FLAGS + [src, "-o", binary],
        capture_output=True, text=True, timeout=60
    )
    assert comp.returncode == 0, (
        f"Compilation of {test_name} failed:\n{comp.stderr}"
    )

    # Run
    run = subprocess.run(
        [binary], capture_output=True, text=True, timeout=timeout
    )
    combined = run.stdout + "\n" + run.stderr
    assert run.returncode == 0, (
        f"Test {test_name} failed (exit {run.returncode}):\n{combined}"
    )
    assert "PASS" in run.stdout, (
        f"Test {test_name} did not print PASS:\n{combined}"
    )


def test_basic_operations():
    """Single-threaded correctness: insert, get, update, erase, re-insert."""
    compile_and_run("test_basic")


def test_concurrent_inserts():
    """Multi-threaded: 4 threads insert disjoint keys, erase half, verify all."""
    compile_and_run("test_concurrent")


def test_resize_under_concurrency():
    """Small initial capacity with concurrent inserts forcing many resizes."""
    compile_and_run("test_resize")
