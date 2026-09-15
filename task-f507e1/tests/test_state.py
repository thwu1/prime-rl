
import subprocess
import os
import re
import pytest

COMPILER_DIR = '/app/Compiler'
TEST_DIR = '/app/test_programs'


def compile_and_run(name):
    """Compile and run a MicroJava test program, return actual output."""
    mj_file = os.path.join(TEST_DIR, f'{name}.mj')
    obj_file = os.path.join(TEST_DIR, f'{name}.obj')
    expected_file = os.path.join(TEST_DIR, f'{name}.expected')

    with open(expected_file) as f:
        expected = f.read().strip()

    # Compile the MicroJava program
    result = subprocess.run(
        ['java', '-cp', COMPILER_DIR, 'MJ.Compiler', mj_file],
        capture_output=True, text=True, timeout=30
    )
    compile_output = result.stdout + result.stderr
    assert '-- line' not in result.stdout, (
        f"Compilation of {name}.mj produced errors:\n{compile_output}"
    )
    assert os.path.exists(obj_file), (
        f"Object file {obj_file} not created. Compiler output:\n{compile_output}"
    )

    # Run the compiled program on the MicroJava VM
    result = subprocess.run(
        ['java', '-cp', COMPILER_DIR, 'MJ.Run', obj_file],
        capture_output=True, text=True, timeout=30
    )

    # Strip VM timing message
    output = result.stdout
    output = re.sub(r'\n?Completion took \d+ ms\s*$', '', output)

    assert output == expected, (
        f"Program {name}.mj output mismatch.\n"
        f"Expected: '{expected}'\n"
        f"Actual:   '{output}'"
    )


def test_bool_basic():
    """Boolean variables, true/false constants, assignment from comparison, use in conditions."""
    compile_and_run('test_bool_basic')


def test_bool_compound():
    """Compound boolean expressions with && and ||, short-circuit, parenthesized sub-expressions."""
    compile_and_run('test_bool_compound')


def test_bool_while():
    """Boolean variable controlling a while loop."""
    compile_and_run('test_bool_while')


def test_enum():
    """Enum declaration, constant access, assignment, comparison, printing."""
    compile_and_run('test_enum')


def test_combined():
    """Both features interacting: enum comparisons assigned to boolean variables."""
    compile_and_run('test_combined')
