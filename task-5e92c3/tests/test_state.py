
import os
import subprocess
import pytest

COMPILER = '/app/compiler.py'
RUNTIME = '/app/runtime.c'
TEST_DIR = '/app/tests'
BUILD_DIR = '/tmp/ll_build'

os.makedirs(BUILD_DIR, exist_ok=True)

# (test_name, expected_exit_code, expected_stdout_or_None)
TESTS = [
    ('test01_return', 42, None),
    ('test02_arith', 42, None),
    ('test03_chain', 49, None),
    ('test04_call', 42, None),
    ('test05_branch', 42, None),
    ('test06_memory', 42, None),
    ('test07_loop', 55, None),
    ('test08_global', 155, None),
    ('test09_factorial', 120, None),
    ('test10_array', 60, None),
    ('test11_bitwise', 159, None),
    ('test12_six_args', 21, None),
    ('test13_eight_args', 36, None),
    ('test14_cmp_ops', 4, None),
    ('test15_fib_print', 55, '55\n'),
]


def test_compiler_exists():
    """The compiler script must exist at /app/compiler.py."""
    assert os.path.isfile(COMPILER), (
        f'Compiler not found at {COMPILER}. '
        'You must create a Python compiler invocable as: '
        'python3 /app/compiler.py <input.ll> -o <output.s>'
    )


@pytest.mark.parametrize('name,expected_exit,expected_stdout', TESTS,
                         ids=[t[0] for t in TESTS])
def test_ll_program(name, expected_exit, expected_stdout):
    ll_file = os.path.join(TEST_DIR, f'{name}.ll')
    asm_file = os.path.join(BUILD_DIR, f'{name}.s')
    exe_file = os.path.join(BUILD_DIR, name)

    assert os.path.isfile(ll_file), f'Test file not found: {ll_file}'

    # Step 1: Compile .ll -> .s
    comp = subprocess.run(
        ['python3', COMPILER, ll_file, '-o', asm_file],
        capture_output=True, text=True, timeout=60,
    )
    assert comp.returncode == 0, (
        f'Compiler failed on {name}.ll\n'
        f'stdout: {comp.stdout}\n'
        f'stderr: {comp.stderr}'
    )
    assert os.path.isfile(asm_file), f'Compiler did not produce {asm_file}'

    # Step 2: Assemble and link .s + runtime.c -> executable
    link = subprocess.run(
        ['gcc', '-o', exe_file, asm_file, RUNTIME, '-no-pie'],
        capture_output=True, text=True, timeout=60,
    )
    assert link.returncode == 0, (
        f'Linking failed on {name}\n'
        f'stdout: {link.stdout}\n'
        f'stderr: {link.stderr}'
    )

    # Step 3: Run the executable and check results
    run = subprocess.run(
        [exe_file],
        capture_output=True, text=True, timeout=30,
    )

    assert run.returncode == expected_exit, (
        f'{name}: expected exit code {expected_exit}, got {run.returncode}\n'
        f'stdout: {run.stdout}\n'
        f'stderr: {run.stderr}'
    )

    if expected_stdout is not None:
        assert run.stdout == expected_stdout, (
            f'{name}: expected stdout {expected_stdout!r}, '
            f'got {run.stdout!r}'
        )
