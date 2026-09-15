"""
Verification tests for the constexpr expression compiler with
control flow and scoping.

Each test compiles a C++ test program whose static_assert statements
verify compile-time correctness. Compilation success == assertions hold.
"""


import subprocess
import pytest
import os

TEST_FILES = [
    "test_arithmetic",
    "test_variables",
    "test_functions",
    "test_power",
    "test_comparisons",
    "test_ternary",
    "test_letbind",
    "test_constfold",
    "test_complex",
]


@pytest.fixture(autouse=True)
def work_in_app():
    os.chdir("/app")
    yield


def compile_and_run(src_path, out_path):
    """Compile a C++ source file and run the resulting binary."""
    comp = subprocess.run(
        ["g++", "-std=c++20", "-Wall", "-Wextra",
         "-I", "/app/include", "-o", out_path, src_path],
        capture_output=True, text=True, timeout=120,
    )
    assert comp.returncode == 0, (
        f"Compilation of {src_path} failed:\n{comp.stderr}"
    )
    run = subprocess.run(
        [out_path], capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, (
        f"Runtime failure for {out_path}:\n{run.stderr}"
    )


@pytest.mark.parametrize("name", TEST_FILES)
def test_individual(name):
    """Each test_*.cpp must compile (static_asserts pass) and run."""
    compile_and_run(f"/app/tests/{name}.cpp", f"/app/{name}")


def test_makefile():
    """Verify make test works end-to-end."""
    subprocess.run(
        ["make", "clean"], cwd="/app",
        capture_output=True, text=True, timeout=30,
    )
    result = subprocess.run(
        ["make", "test"], cwd="/app",
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"make test failed:\n{result.stdout}\n{result.stderr}"
    )
