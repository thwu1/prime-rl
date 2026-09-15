
"""
Tests for the algebraic effect handler interpreter.
Verifies correct evaluation of HandleExpr and DoExpr by running example
programs and checking output, plus targeted semantic tests.
"""

import subprocess
import os
import sys
import glob

sys.path.insert(0, "/app")

EXAMPLES_DIR = "/app/examples"


def run_program(source_code):
    """Run a source program and return its output."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.eff', delete=False, dir='/tmp') as f:
        f.write(source_code)
        f.flush()
        tmp = f.name
    try:
        result = subprocess.run(
            ["python3", "/app/run.py", tmp],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    finally:
        os.unlink(tmp)


def run_example(name):
    """Run an example .eff file and compare to .expected."""
    eff_path = os.path.join(EXAMPLES_DIR, name + ".eff")
    exp_path = os.path.join(EXAMPLES_DIR, name + ".expected")
    with open(exp_path) as f:
        expected = f.read().strip()
    stdout, stderr, rc = run_program(open(eff_path).read())
    return stdout, expected, stderr, rc


class TestBasicExpressions:
    """Test that basic (non-effect) expressions still work."""

    def test_01_basic_arithmetic(self):
        stdout, expected, stderr, rc = run_example("01_basic")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected


class TestSimpleHandlers:
    """Test basic effect handler patterns."""

    def test_02_state_effect(self):
        """State effect using state-passing style handler."""
        stdout, expected, stderr, rc = run_example("02_state")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_03_exception_effect(self):
        """Exception effect: handler discards continuation."""
        stdout, expected, stderr, rc = run_example("03_exception")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_10_return_clause(self):
        """Return clause transforms the body's normal return value."""
        stdout, expected, stderr, rc = run_example("10_return_clause")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected


class TestMultiShotContinuations:
    """Test that resume can be called multiple times."""

    def test_04_choice_effect(self):
        """Choose effect: resume called twice per operation (multi-shot)."""
        stdout, expected, stderr, rc = run_example("04_choice")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_multi_shot_three_way(self):
        """Resume called three times."""
        src = '''
effect Pick { Choose() }
val r = handle {
    do Choose()
} with Pick {
    return(x) => x ++ ""
    Choose(resume) => resume(1) ++ "," ++ resume(2) ++ "," ++ resume(3)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "1,2,3"


class TestContinuationDiscarding:
    """Test zero-shot: handler ignores resume."""

    def test_07_discard(self):
        """Break effect: handler discards continuation to exit loop."""
        stdout, expected, stderr, rc = run_example("07_discard")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_exception_discards_continuation(self):
        """Verify computation after do is never executed when resume is not called."""
        src = '''
effect Exc { Throw(msg) }
val r = handle {
    print("before");
    do Throw("err");
    print("SHOULD NOT APPEAR")
} with Exc {
    return(x) => "ok"
    Throw(msg, resume) => msg
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert "SHOULD NOT APPEAR" not in stdout
        assert stdout == "before\nerr"


class TestNestedHandlers:
    """Test nested handler scoping."""

    def test_05_nested_same_effect(self):
        """Inner handler shadows outer for the same effect."""
        stdout, expected, stderr, rc = run_example("05_nested")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_nested_different_values(self):
        """Nested handlers for same effect provide different values."""
        src = '''
effect E { Ask() }
val r = handle {
    val outer = do Ask();
    val inner = handle {
        do Ask()
    } with E {
        return(x) => x
        Ask(resume) => resume(200)
    };
    outer + inner
} with E {
    return(x) => x
    Ask(resume) => resume(100)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "300"


class TestMultiOperationHandlers:
    """Test handlers with multiple operation clauses."""

    def test_06_multi_op(self):
        stdout, expected, stderr, rc = run_example("06_multi_op")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_two_ops_same_handler(self):
        """Handler defines two operations, both are used."""
        src = '''
effect Counter {
    Inc();
    Read()
}
val r = handle {
    do Inc();
    do Inc();
    do Inc();
    do Read()
} with Counter {
    return(x) => fun(n) => x
    Inc(resume) => fun(n) => resume(unit)(n + 1)
    Read(resume) => fun(n) => resume(n)(n)
};
print(r(0))
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "3"


class TestCollect:
    """Test collect/yield pattern."""

    def test_08_collect(self):
        stdout, expected, stderr, rc = run_example("08_collect")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected


class TestCrossEffectInteraction:
    """Test that different effects correctly propagate to their handlers."""

    def test_09_two_effects(self):
        stdout, expected, stderr, rc = run_example("09_two_effects")
        assert rc == 0, f"Program failed: {stderr}"
        assert stdout == expected

    def test_two_separate_effects(self):
        """Two different effects handled by two separate handlers."""
        src = '''
effect A { GetA() }
effect B { GetB() }
val r = handle {
    handle {
        do GetA() + do GetB()
    } with B {
        return(x) => x
        GetB(resume) => resume(20)
    }
} with A {
    return(x) => x
    GetA(resume) => resume(10)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "30"


class TestReinstallation:
    """Test that handler is re-installed when resume is called."""

    def test_handler_reinstalled_on_resume(self):
        """Multiple operations in body are all caught by the same handler."""
        src = '''
effect E { Op() }
val r = handle {
    do Op() + do Op() + do Op()
} with E {
    return(x) => x
    Op(resume) => resume(10)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "30"

    def test_state_counter(self):
        """State handler with multiple get/set operations."""
        src = '''
effect S { Get(); Set(v) }
val prog = handle {
    val a = do Get();
    do Set(a + 10);
    val b = do Get();
    do Set(b + 20);
    do Get()
} with S {
    return(x) => fun(s) => x
    Get(resume) => fun(s) => resume(s)(s)
    Set(v, resume) => fun(s) => resume(unit)(v)
};
print(prog(0))
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "30"


class TestEdgeCases:
    """Edge cases and complex interactions."""

    def test_handle_no_effects(self):
        """Body performs no operations — return clause still applies."""
        src = '''
effect E { Op() }
val r = handle {
    42
} with E {
    return(x) => x * 2
    Op(resume) => resume(0)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "84"

    def test_resume_with_unit(self):
        """Resume with unit value."""
        src = '''
effect E { Log(msg) }
handle {
    do Log("hello");
    do Log("world")
} with E {
    return(x) => unit
    Log(msg, resume) => (print(msg); resume(unit))
}
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "hello\nworld"

    def test_nested_choice_small(self):
        """Nested multi-shot: two levels of choice."""
        src = '''
effect C { Pick() }
val r = handle {
    val x = do Pick();
    if x then "A" else "B"
} with C {
    return(x) => x
    Pick(resume) => resume(true) ++ resume(false)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "AB"

    def test_handler_with_only_return(self):
        """Handler that only has a return clause, no operation clauses."""
        src = '''
effect E { Op() }
val r = handle {
    100
} with E {
    return(x) => x + 1
    Op(resume) => resume(0)
};
print(r)
'''
        stdout, _, rc = run_program(src)
        assert rc == 0
        assert stdout == "101"


class TestAllExamples:
    """Run all .eff examples and verify against .expected files."""

    def test_all_examples_pass(self):
        eff_files = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.eff")))
        failures = []
        for eff_file in eff_files:
            name = os.path.basename(eff_file)
            exp_file = eff_file.replace(".eff", ".expected")
            if not os.path.exists(exp_file):
                continue
            with open(exp_file) as f:
                expected = f.read().strip()
            with open(eff_file) as f:
                source = f.read()
            stdout, stderr, rc = run_program(source)
            if rc != 0 or stdout != expected:
                failures.append((name, expected, stdout, stderr))
        assert not failures, \
            "Examples failed:\n" + "\n".join(
                f"  {n}: expected={e!r}, got={g!r}, stderr={s!r}"
                for n, e, g, s in failures
            )
