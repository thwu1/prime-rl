
import subprocess
import os
import pytest

COMPILER = "/app/sysy_compiler"
RUNNER = "/app/sysy_run"
MAKEFILE = "/app/Makefile"
RUNTIME_BC = "/app/runtime/sylib.bc"
TEST_DIR = "/app/test_programs"
INPUT_DIR = "/app/test_inputs"


def run_sysy(program, stdin_data=None, timeout=30):
    """Run a SysY program through the full pipeline and return (stdout, exit_code)."""
    result = subprocess.run(
        [RUNNER, os.path.join(TEST_DIR, program)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout, result.returncode


# ── Pipeline infrastructure tests ──────────────────────────────────


def test_makefile_exists():
    """A Makefile must exist at /app/Makefile."""
    assert os.path.isfile(MAKEFILE), f"Makefile not found at {MAKEFILE}"


def test_make_succeeds():
    """Running make must succeed and produce runtime bitcode."""
    result = subprocess.run(
        ["make", "-C", "/app"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"make failed: {result.stderr}"


def test_runtime_bitcode_exists():
    """After make, the runtime bitcode must exist."""
    assert os.path.isfile(RUNTIME_BC), f"Runtime bitcode not found at {RUNTIME_BC}"


def test_compiler_exists():
    """The compiler executable must exist and be runnable."""
    assert os.path.isfile(COMPILER), f"Compiler not found at {COMPILER}"
    assert os.access(COMPILER, os.X_OK), f"Compiler at {COMPILER} is not executable"


def test_compiler_produces_llvm_ir():
    """The compiler must produce valid LLVM IR that llvm-as accepts."""
    # Compile a simple program
    comp = subprocess.run(
        [COMPILER, os.path.join(TEST_DIR, "01_basic_arith.sy")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert comp.returncode == 0, f"Compiler failed: {comp.stderr}"
    ir = comp.stdout
    assert "define" in ir, "Output does not look like LLVM IR (no 'define')"
    # Validate with llvm-as
    asm = subprocess.run(
        ["llvm-as", "-o", "/dev/null"],
        input=ir,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert asm.returncode == 0, f"llvm-as rejected the IR: {asm.stderr}"


def test_runner_exists():
    """The pipeline runner script must exist and be executable."""
    assert os.path.isfile(RUNNER), f"Runner not found at {RUNNER}"
    assert os.access(RUNNER, os.X_OK), f"Runner at {RUNNER} is not executable"


# ── Functional correctness tests ───────────────────────────────────


def test_01_basic_arith():
    """Arithmetic operators, putint/putch, non-zero return code."""
    stdout, rc = run_sysy("01_basic_arith.sy")
    assert stdout == "13\n7\n30\n3\n1\n"
    assert rc == 42


def test_02_scoping():
    """Variable shadowing across global, local, and nested block scopes."""
    stdout, rc = run_sysy("02_scoping.sy")
    assert stdout == "1\n2\n3\n2\n"
    assert rc == 0


def test_03_array_init():
    """Multi-dimensional array initialization with mixed braced/unbraced values."""
    stdout, rc = run_sysy("03_array_init.sy")
    assert stdout == "1 2 3 0 5 0 7 8 \n"
    assert rc == 0


def test_04_recursive():
    """Recursive function calls (GCD algorithm)."""
    stdout, rc = run_sysy("04_recursive.sy")
    assert stdout == "4\n25\n1\n"
    assert rc == 0


def test_05_loops():
    """While loop with break and continue, correct sum and loop variable."""
    stdout, rc = run_sysy("05_loops.sy")
    assert stdout == "37\n11\n"
    assert rc == 0


def test_06_short_circuit():
    """Short-circuit evaluation of || and && with side-effecting function."""
    stdout, rc = run_sysy("06_short_circuit.sy")
    assert stdout == "0\n0\n1\n2\n"
    assert rc == 0


def test_07_array_param():
    """Arrays passed by reference to functions, modification visible to caller."""
    stdout, rc = run_sysy("07_array_param.sy")
    assert stdout == "30\n"
    assert rc == 0


def test_08_const_expr():
    """Const declarations, const array initialized with const expressions."""
    stdout, rc = run_sysy("08_const_expr.sy")
    assert stdout == "5 11 16\n"
    assert rc == 0


def test_09_number_formats():
    """Hexadecimal (0xFF) and octal (077) integer literal parsing."""
    stdout, rc = run_sysy("09_number_formats.sy")
    assert stdout == "255\n63\n255\n1\n"
    assert rc == 0


def test_10_global_init():
    """Global variables: default zero, explicit init, partial array init."""
    stdout, rc = run_sysy("10_global_init.sy")
    assert stdout == "0 10 1 2 3 0 0\n"
    assert rc == 0


def test_11_unary_ops():
    """Unary operators: negation, positive, logical not, double not."""
    stdout, rc = run_sysy("11_unary_ops.sy")
    assert stdout == "-5\n5\n0\n1\n1\n"
    assert rc == 0


def test_12_input_test():
    """Reading integers from stdin with getint()."""
    stdout, rc = run_sysy("12_input_test.sy", stdin_data="3\n10\n20\n30\n")
    assert stdout == "60\n"
    assert rc == 0
