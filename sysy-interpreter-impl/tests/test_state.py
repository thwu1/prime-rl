
import subprocess
import os
import tempfile
import pytest

COMPILER = '/app/sysyc'
RUNTIME_BC = '/app/runtime/sylib.bc'
TEST_DIR = '/app/tests'

# Each entry: (expected_stdout, expected_retcode)
EXPECTED = {
    'test_00_basic_return.sy': ('', 42),
    'test_01_arithmetic.sy': ('14\n20\n3\n1\n', 0),
    'test_02_if_else.sy': ('1\n0\n', 0),
    'test_03_while_loop.sy': ('45\n', 0),
    'test_04_recursion.sy': ('12\n', 0),
    'test_05_array_init_2d.sy': ('1 2 3 0 5 0 \n', 0),
    'test_06_short_circuit.sy': ('0\n0\n1\n2\n', 0),
    'test_07_scoping.sy': ('1\n2\n3\n2\n', 0),
    'test_08_array_param.sy': ('0 1 4 9 16 \n', 0),
    'test_09_break_continue.sy': ('25\n', 0),
    'test_10_hex_octal.sy': ('26 26 26\n', 0),
    'test_11_fibonacci.sy': ('0 1 1 2 3 5 8 13 21 34 \n', 0),
    'test_12_unary_ops.sy': ('-5\n5\n0\n1\n1\n', 0),
    'test_13_neg_div_mod.sy': ('-3\n-1\n-3\n1\n', 0),
    'test_14_prime_count.sy': ('25\n', 0),
    'test_15_const_array_dim.sy': ('100\n11\n', 0),
    'test_16_array_init_complex.sy': ('0 0 3 4 5 6 0 0 \n', 0),
    'test_17_void_func.sy': ('1 2 3 4 5 \n10 11 12 \n', 0),
    'test_18_matrix_param.sy': ('1 2 3 \n4 5 6 \n', 0),
    'test_19_global_init.sy': ('0 0 0 0 0 \n42\n', 0),
    'test_20_large_return.sy': ('', 44),
    'test_21_const_array.sy': ('60\n', 0),
    'test_22_scope_array_func.sy': ('15\n60\n15\n', 0),
}


def compile_and_run(sy_file, stdin_data=''):
    """Run the full LLVM toolchain pipeline: sysyc -> llvm-as -> llvm-link -> lli."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ll_file = os.path.join(tmpdir, 'out.ll')
        bc_file = os.path.join(tmpdir, 'out.bc')
        linked_file = os.path.join(tmpdir, 'linked.bc')

        # Step 1: Compile SysY to LLVM IR
        r = subprocess.run(
            [COMPILER, sy_file],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"Compiler failed on {sy_file}:\nstderr: {r.stderr}\nstdout: {r.stdout[:500]}"
        )
        with open(ll_file, 'w') as f:
            f.write(r.stdout)

        # Step 2: Assemble LLVM IR to bitcode
        r = subprocess.run(
            ['llvm-as', ll_file, '-o', bc_file],
            capture_output=True, text=True, timeout=30,
        )
        ir_snippet = open(ll_file).read()[:2000] if os.path.exists(ll_file) else '<empty>'
        assert r.returncode == 0, (
            f"llvm-as failed:\n{r.stderr}\nIR (first 2000 chars):\n{ir_snippet}"
        )

        # Step 3: Link with SysY runtime
        r = subprocess.run(
            ['llvm-link', bc_file, RUNTIME_BC, '-o', linked_file],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"llvm-link failed:\n{r.stderr}"

        # Step 4: Execute via LLVM interpreter
        r = subprocess.run(
            ['lli', linked_file],
            input=stdin_data, capture_output=True, text=True, timeout=30,
        )
        return r.stdout, r.returncode


def test_compiler_exists():
    """The compiler executable must exist and be executable."""
    assert os.path.exists(COMPILER), f"Compiler not found at {COMPILER}"
    assert os.access(COMPILER, os.X_OK), f"Compiler at {COMPILER} is not executable"


def test_runtime_bitcode_exists():
    """The SysY runtime bitcode must exist."""
    assert os.path.exists(RUNTIME_BC), f"Runtime bitcode not found at {RUNTIME_BC}"


def test_llvm_tools_available():
    """Required LLVM tools must be on PATH."""
    for tool in ['llvm-as', 'llvm-link', 'lli']:
        r = subprocess.run(['which', tool], capture_output=True)
        assert r.returncode == 0, f"LLVM tool not found: {tool}"


@pytest.mark.parametrize("test_name", sorted(EXPECTED.keys()))
def test_sysy_program(test_name):
    """Compile a SysY program through the full LLVM pipeline and verify output."""
    sy_file = os.path.join(TEST_DIR, test_name)
    expected_stdout, expected_retcode = EXPECTED[test_name]

    assert os.path.exists(sy_file), f"Test file not found: {sy_file}"

    stdout, retcode = compile_and_run(sy_file)

    assert stdout == expected_stdout, (
        f"stdout mismatch for {test_name}:\n"
        f"  expected: {expected_stdout!r}\n"
        f"  actual:   {stdout!r}"
    )
    assert retcode == expected_retcode, (
        f"return code mismatch for {test_name}: "
        f"expected {expected_retcode}, got {retcode}"
    )
