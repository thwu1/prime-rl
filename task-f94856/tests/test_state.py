
import os
import subprocess
import pytest

COMPILER = "/app/compile.py"
PROGRAMS_DIR = "/app/programs"
RUNTIME = "/app/runtime.c"

EXPECTED_OUTPUT = {
    "ret42.ll": "42\n",
    "arith.ll": "42\n",
    "branch.ll": "42\n",
    "factorial.ll": "120\n3628800\n0\n",
    "arrays.ll": "150\n",
    "mutual_rec.ll": "1\n0\n0\n1\n0\n",
    "alloca.ll": "17\n",
    "fib.ll": "610\n",
    "globals.ll": "5\n",
}


def test_compiler_exists():
    """The compiler script must exist and be executable."""
    assert os.path.exists(COMPILER), f"Compiler not found at {COMPILER}"
    assert os.access(COMPILER, os.X_OK), f"{COMPILER} is not executable"


@pytest.mark.parametrize("prog_name,expected", list(EXPECTED_OUTPUT.items()))
def test_program_output(prog_name, expected, tmp_path):
    """Compile an LLVMlite IR program, link with runtime, and verify output."""
    ll_file = os.path.join(PROGRAMS_DIR, prog_name)
    s_file = str(tmp_path / "output.s")
    exe_file = str(tmp_path / "output")

    # Step 1: Compile .ll to .s
    result = subprocess.run(
        [COMPILER, ll_file, s_file],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Compilation of {prog_name} failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(s_file), f"Compiler did not produce {s_file}"

    # Step 2: Assemble and link with gcc
    result = subprocess.run(
        ["gcc", "-o", exe_file, s_file, RUNTIME, "-no-pie"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Assembly/linking of {prog_name} failed (exit {result.returncode}):\n"
        f"stderr: {result.stderr}"
    )

    # Step 3: Run the executable and check output
    result = subprocess.run(
        [exe_file],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Execution of {prog_name} binary failed with exit code {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout == expected, (
        f"Output mismatch for {prog_name}:\n"
        f"Expected: {expected!r}\n"
        f"Got:      {result.stdout!r}"
    )
