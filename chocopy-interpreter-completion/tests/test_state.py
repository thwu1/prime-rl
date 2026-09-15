
import subprocess
import os
import pytest

TRANSPILER = "/app/transpile.py"
PROGRAMS_DIR = "/app/programs"
RUNTIME_DIR = "/app/runtime"
BUILD_DIR = "/app/build"
TIMEOUT = 60


def compile_and_run(name):
    """Transpile a ChocoPy program to C, compile with gcc, and run."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    src = os.path.join(PROGRAMS_DIR, name)
    base = name.replace(".py", "")
    c_file = os.path.join(BUILD_DIR, f"{base}.c")
    binary = os.path.join(BUILD_DIR, base)

    # Step 1: Transpile ChocoPy -> C
    r = subprocess.run(
        ["python3", TRANSPILER, src, c_file],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert r.returncode == 0, (
        f"Transpilation failed for {name}:\nstderr:\n{r.stderr}\nstdout:\n{r.stdout}"
    )

    # Step 2: Compile C -> binary
    r = subprocess.run(
        [
            "gcc",
            "-std=c99",
            "-Wall",
            "-Wno-unused-variable",
            "-g",
            "-I",
            RUNTIME_DIR,
            c_file,
            os.path.join(RUNTIME_DIR, "runtime.c"),
            "-o",
            binary,
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert r.returncode == 0, (
        f"gcc compilation failed for {name}:\nstderr:\n{r.stderr}"
    )

    # Step 3: Run binary
    return subprocess.run(
        [binary], capture_output=True, text=True, timeout=TIMEOUT
    )


# ------------------------------------------------------------------ #
# Expected outputs for programs that should succeed                   #
# ------------------------------------------------------------------ #

EXPECTED_OUTPUTS = {
    "basic.py": "52\n32\n420\n4\n2\n-42\nTrue\nFalse\n",
    "strings.py": "Hello World\n5\n11\nTrue\nTrue\n",
    "control.py": "1\n6\n5\n1\nFalse\nTrue\nTrue\n",
    "functions.py": "120\n1\n55\nTrue\nTrue\n",
    "classes.py": (
        "Woof\n"
        "Woof\n"
        "Cat says: Meow\n"
        "Cat says: Meow\n"
        "1\n"
        "2\n"
        "2\n"
    ),
    "lists.py": "1\n5\n5\n7\n6\n7\n99\n1\n113\n",
    "misc.py": (
        "True\n"
        "False\n"
        "True\n"
        "False\n"
        "True\n"
        "a\n"
        "e\n"
        "5\n"
        "5\n"
        "e\n"
        "7\n"
        "7\n"
    ),
}

# ------------------------------------------------------------------ #
# Expected errors for programs that should fail at runtime            #
# ------------------------------------------------------------------ #

EXPECTED_ERRORS = {
    "err_divzero.py": ("Division by zero", 2),
    "err_none.py": ("Operation on None", 4),
    "err_index.py": ("Index out of bounds", 3),
}


# ------------------------------------------------------------------ #
# Tests for successful programs                                       #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("program,expected", list(EXPECTED_OUTPUTS.items()))
def test_successful_program(program, expected):
    result = compile_and_run(program)
    assert result.returncode == 0, (
        f"{program}: expected exit 0 but got {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.stdout == expected, (
        f"{program}: output mismatch\n"
        f"expected:\n{expected!r}\n"
        f"got:\n{result.stdout!r}"
    )


# ------------------------------------------------------------------ #
# Tests for runtime-error programs                                    #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "program,error_spec", list(EXPECTED_ERRORS.items())
)
def test_runtime_error(program, error_spec):
    error_msg, exit_code = error_spec
    result = compile_and_run(program)
    assert result.returncode == exit_code, (
        f"{program}: expected exit code {exit_code} but got {result.returncode}\n"
        f"stderr:\n{result.stderr}"
    )
    assert error_msg in result.stderr, (
        f"{program}: expected '{error_msg}' in stderr\n"
        f"got:\n{result.stderr}"
    )
