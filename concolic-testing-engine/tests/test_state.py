"""
Tests for the automated bug finder.


Verifies that find_bug() discovers inputs triggering assertion failures
in target programs, then confirms via the concrete interpreter.
"""

import sys
import os
import tempfile
import importlib

sys.path.insert(0, '/app')
from interpreter import parse, execute


PROGRAMS_DIR = '/app/programs'


def _load_bugfinder():
    """Import or reload the bugfinder module."""
    if 'bugfinder' in sys.modules:
        return importlib.reload(sys.modules['bugfinder'])
    import bugfinder
    return bugfinder


def _verify_from_file(prog_path):
    """Run find_bug on a program file and verify the result triggers assertion failure."""
    bf = _load_bugfinder()
    assert os.path.exists(prog_path), (
        f"Program file not found: {prog_path}"
    )
    with open(prog_path, 'r') as f:
        source = f.read()
    program = parse(source)

    inputs = bf.find_bug(prog_path)

    assert inputs is not None, (
        f"find_bug returned None for {os.path.basename(prog_path)} — no triggering inputs found"
    )
    assert isinstance(inputs, (list, tuple)), (
        f"find_bug must return a list of integers, got {type(inputs)}"
    )
    int_inputs = [int(x) for x in inputs]

    try:
        status, assertion_failed, env = execute(program, int_inputs)
    except RuntimeError as e:
        raise AssertionError(
            f"Interpreter raised error with inputs {int_inputs}: {e}"
        )

    assert assertion_failed, (
        f"Inputs {int_inputs} did not trigger an assertion failure in "
        f"{os.path.basename(prog_path)}. Status: {status}, env: {env}"
    )


def _verify_from_source(source_text):
    """Write source to temp file, run find_bug, verify assertion failure is triggered."""
    bf = _load_bugfinder()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.prog', delete=False, dir='/tmp') as f:
        f.write(source_text)
        tmp_path = f.name
    try:
        program = parse(source_text)
        inputs = bf.find_bug(tmp_path)

        assert inputs is not None, (
            "find_bug returned None for unseen program — no triggering inputs found"
        )
        assert isinstance(inputs, (list, tuple)), (
            f"find_bug must return a list of integers, got {type(inputs)}"
        )
        int_inputs = [int(x) for x in inputs]

        try:
            status, assertion_failed, env = execute(program, int_inputs)
        except RuntimeError as e:
            raise AssertionError(
                f"Interpreter raised error with inputs {int_inputs}: {e}"
            )

        assert assertion_failed, (
            f"Inputs {int_inputs} did not trigger assertion failure. "
            f"Status: {status}, env: {env}"
        )
    finally:
        os.unlink(tmp_path)


# ── Structural checks ───────────────────────────────────────────────

def test_bugfinder_exists():
    assert os.path.exists('/app/bugfinder.py'), (
        "bugfinder.py not found at /app/bugfinder.py"
    )


def test_find_bug_callable():
    bf = _load_bugfinder()
    assert callable(getattr(bf, 'find_bug', None)), (
        "bugfinder.py must define a callable find_bug(program_path) function"
    )


# ── Shipped target programs ─────────────────────────────────────────

def test_target_1():
    _verify_from_file(os.path.join(PROGRAMS_DIR, 'target_1.prog'))


def test_target_2():
    _verify_from_file(os.path.join(PROGRAMS_DIR, 'target_2.prog'))


def test_target_3():
    _verify_from_file(os.path.join(PROGRAMS_DIR, 'target_3.prog'))


def test_target_4():
    _verify_from_file(os.path.join(PROGRAMS_DIR, 'target_4.prog'))


def test_target_5():
    _verify_from_file(os.path.join(PROGRAMS_DIR, 'target_5.prog'))


# ── Hidden programs (not present in Docker image) ───────────────────

_HIDDEN_PROG_A = """\
a = input()
b = input()
s = a + b
t30 = 30
if s != t30 goto end
p = a * b
t221 = 221
if p != t221 goto end
t0 = 0
t1 = 1
assert t0 == t1
end:
halt
"""

_HIDDEN_PROG_B = """\
n = input()
s = 0
i = 0
t1 = 1
loop:
if i >= n goto done
s = s + i
i = i + t1
goto loop
done:
t45 = 45
if s != t45 goto end
t0 = 0
t2 = 1
assert t0 == t2
end:
halt
"""

_HIDDEN_PROG_C = """\
x = input()
y = input()
z = input()
t1 = 1
if x < t1 goto end
t50 = 50
if x > t50 goto end
p = x * y
s = p + z
t247 = 247
if s != t247 goto end
d = x - z
t11 = 11
if d != t11 goto end
t0 = 0
t2 = 1
assert t0 == t2
end:
halt
"""


def test_hidden_a():
    _verify_from_source(_HIDDEN_PROG_A)


def test_hidden_b():
    _verify_from_source(_HIDDEN_PROG_B)


def test_hidden_c():
    _verify_from_source(_HIDDEN_PROG_C)
