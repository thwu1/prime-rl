"""
Test suite for algebraic effect handler runtime.

Part A: Prolog cross-verification tests — dynamically compares Python
behavior against SWI-Prolog reference programs using reset/3 and shift/1.

Part B: Core implementation tests — covers basic handling, resume
semantics, sequential effects, nested handlers, shadowing, forwarding,
state effects, collector effects, multi-shot continuations, and effect
identity.
"""

import sys
sys.path.insert(0, '/app')

import subprocess
import re
import pytest
from effects import Effect, perform, handle


# ---------------------------------------------------------------------------
# Helper: run a Prolog program with swipl and return stdout
# ---------------------------------------------------------------------------

def run_prolog(filepath):
    """Execute a Prolog file with swipl and return its stdout."""
    result = subprocess.run(
        ['swipl', filepath],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"swipl {filepath} failed (rc={result.returncode}):\n{result.stderr}"
    )
    return result.stdout


# ===================================================================
# Part A: Prolog cross-verification tests
# ===================================================================

class TestPrologCrossVerification:
    """Verify Python implementation matches SWI-Prolog reference output."""

    def test_state_handler_from_zero(self):
        """State handler starting from 0: final value must match Prolog."""
        output = run_prolog('/app/reference/state_handler.pl')
        m = re.search(r'init=0\s+final=(\d+)', output)
        assert m, f"Cannot parse state_handler.pl output:\n{output}"
        expected = int(m.group(1))

        Get = Effect("Get")
        Set = Effect("Set")

        def body():
            x = perform(Get, None)
            perform(Set, x + 1)
            y = perform(Get, None)
            perform(Set, y * 2)
            return perform(Get, None)

        state = [0]

        def get_h(_, resume):
            return resume(state[0])

        def set_h(v, resume):
            state[0] = v
            return resume(None)

        result = handle(body, {Get: get_h, Set: set_h})
        assert result == expected

    def test_state_handler_from_ten(self):
        """State handler starting from 10: final value must match Prolog."""
        output = run_prolog('/app/reference/state_handler.pl')
        m = re.search(r'init=10\s+final=(\d+)', output)
        assert m, f"Cannot parse state_handler.pl output:\n{output}"
        expected = int(m.group(1))

        Get = Effect("Get")
        Set = Effect("Set")

        def body():
            x = perform(Get, None)
            perform(Set, x + 1)
            y = perform(Get, None)
            perform(Set, y * 2)
            return perform(Get, None)

        state = [10]

        def get_h(_, resume):
            return resume(state[0])

        def set_h(v, resume):
            state[0] = v
            return resume(None)

        result = handle(body, {Get: get_h, Set: set_h})
        assert result == expected

    def test_compose_result(self):
        """Handler result composition must match Prolog reference."""
        output = run_prolog('/app/reference/compose.pl')
        m = re.search(r'compose=(\d+)', output)
        assert m, f"Cannot parse compose.pl output:\n{output}"
        expected = int(m.group(1))

        E = Effect("E")

        def body():
            x = perform(E, 10)
            return x * 3

        def handler(arg, resume):
            result = resume(arg + 5)
            return result + 100

        result = handle(body, {E: handler})
        assert result == expected

    def test_shadowing_values(self):
        """Handler shadowing must match Prolog reference."""
        output = run_prolog('/app/reference/shadowing.pl')
        m_outer = re.search(r'outer=(\w+)', output)
        m_inner = re.search(r'inner=(\w+)', output)
        assert m_outer and m_inner, (
            f"Cannot parse shadowing.pl output:\n{output}"
        )
        prolog_outer = m_outer.group(1)
        prolog_inner = m_inner.group(1)

        Ask = Effect("Ask")

        def body():
            outer_val = perform(Ask, "outer?")

            def inner_body():
                return perform(Ask, "inner?")

            inner_result = handle(inner_body, {
                Ask: lambda q, resume: resume("inner_val")
            })
            return (outer_val, inner_result)

        result = handle(body, {
            Ask: lambda q, resume: resume("outer_val")
        })
        assert result[0] == prolog_outer
        assert result[1] == prolog_inner

    def test_collector_items(self):
        """Collector (emit/collect) pattern must match Prolog reference."""
        output = run_prolog('/app/reference/collector.pl')
        m = re.search(r'collected=\[(.+?)\]', output)
        assert m, f"Cannot parse collector.pl output:\n{output}"
        expected_items = [x.strip() for x in m.group(1).split(',')]

        Emit = Effect("Emit")
        collected = []

        def body():
            for item in expected_items:
                perform(Emit, item)
            return "done"

        result = handle(body, {
            Emit: lambda v, resume: (collected.append(v), resume(None))[1]
        })
        assert result == "done"
        assert collected == expected_items


# ===================================================================
# Part B: Core implementation tests
# ===================================================================

def test_no_effects():
    """handle with no effects in body returns body's result."""
    result = handle(lambda: 42, {})
    assert result == 42


def test_unhandled_effect_raises():
    """Performing an effect with no handler raises RuntimeError."""
    E = Effect("E")
    with pytest.raises(RuntimeError):
        perform(E, "hello")


def test_exception_style():
    """Handler that doesn't call resume abandons the body."""
    Abort = Effect("Abort")

    def body():
        perform(Abort, "something failed")
        return "unreachable"

    result = handle(body, {
        Abort: lambda msg, resume: f"caught: {msg}"
    })
    assert result == "caught: something failed"


def test_single_resume():
    """Handler resumes body with a value."""
    Ask = Effect("Ask")

    def body():
        name = perform(Ask, "your name?")
        return f"Hello, {name}!"

    result = handle(body, {
        Ask: lambda q, resume: resume("World")
    })
    assert result == "Hello, World!"


def test_resume_returns_body_result():
    """resume() returns the eventual result of the body computation."""
    E = Effect("E")

    def body():
        x = perform(E, 10)
        return x * 3

    def handler(arg, resume):
        result = resume(arg + 5)
        return result + 100

    result = handle(body, {E: handler})
    # body: perform(E,10) -> handler gives 15 -> body returns 15*3=45
    # handler: resume(15) returns 45 -> handler returns 45+100=145
    assert result == 145


def test_multiple_sequential_effects():
    """Body performs multiple effects sequentially."""
    Ask = Effect("Ask")

    def body():
        a = perform(Ask, "first")
        b = perform(Ask, "second")
        c = perform(Ask, "third")
        return a + b + c

    result = handle(body, {
        Ask: lambda q, resume: resume(len(q))
    })
    # len("first")=5, len("second")=6, len("third")=5 => 16
    assert result == 16


def test_two_different_effects_one_handler():
    """Single handle call handles two different effect types."""
    Ask = Effect("Ask")
    Tell = Effect("Tell")

    told = []

    def body():
        x = perform(Ask, "question")
        perform(Tell, f"answer is {x}")
        return x

    result = handle(body, {
        Ask: lambda q, resume: resume("42"),
        Tell: lambda msg, resume: (told.append(msg), resume(None))[1]
    })
    assert result == "42"
    assert told == ["answer is 42"]


def test_nested_different_effects():
    """Nested handlers for different effects cooperate correctly."""
    Reader = Effect("Reader")
    Writer = Effect("Writer")

    collected = []

    def body():
        x = perform(Reader, "key")
        perform(Writer, f"read: {x}")
        y = perform(Reader, "key2")
        perform(Writer, f"read: {y}")
        return x + y

    result = handle(
        lambda: handle(body, {
            Reader: lambda k, resume: resume(k.upper())
        }),
        {Writer: lambda msg, resume: (collected.append(msg), resume(None))[1]}
    )
    assert result == "KEYKEY2"
    assert collected == ["read: KEY", "read: KEY2"]


def test_shadowing():
    """Inner handler shadows outer handler for the same effect."""
    Ask = Effect("Ask")

    def body():
        outer_val = perform(Ask, "outer?")

        def inner_body():
            return perform(Ask, "inner?")

        inner_result = handle(inner_body, {
            Ask: lambda q, resume: resume("INNER")
        })
        return (outer_val, inner_result)

    result = handle(body, {
        Ask: lambda q, resume: resume("OUTER")
    })
    assert result == ("OUTER", "INNER")


def test_handler_forwarding():
    """Handler function can perform effects handled by an outer handler."""
    Read = Effect("Read")
    Log = Effect("Log")

    logged = []

    def body():
        x = perform(Read, None)
        return x * 2

    def middle():
        def read_handler(_, resume):
            perform(Log, "about to read")
            return resume(21)
        return handle(body, {Read: read_handler})

    result = handle(middle, {
        Log: lambda msg, resume: (logged.append(msg), resume(None))[1]
    })
    assert result == 42
    assert logged == ["about to read"]


def test_handler_does_not_catch_own_effects():
    """Effects performed by the handler propagate upward, not to itself."""
    E = Effect("E")

    def body():
        return perform(E, "from_body")

    def middle():
        def e_handler(arg, resume):
            x = perform(E, "from_handler")
            return resume(x)
        return handle(body, {E: e_handler})

    result = handle(middle, {
        E: lambda arg, resume: resume(f"outer({arg})")
    })
    assert result == "outer(from_handler)"


def test_state_effect():
    """Stateful get/set effect pattern."""
    Get = Effect("Get")
    Set = Effect("Set")

    def body():
        x = perform(Get, None)
        perform(Set, x + 1)
        y = perform(Get, None)
        perform(Set, y * 2)
        return perform(Get, None)

    def run_with_state(body_fn, initial):
        state = [initial]
        def get_handler(_, resume):
            return resume(state[0])
        def set_handler(v, resume):
            state[0] = v
            return resume(None)
        return handle(body_fn, {Get: get_handler, Set: set_handler})

    assert run_with_state(body, 0) == 2
    assert run_with_state(body, 10) == 22


def test_collector_effect():
    """Emit/collect pattern (writer-like effect)."""
    Emit = Effect("Emit")

    def body():
        perform(Emit, "a")
        perform(Emit, "b")
        perform(Emit, "c")
        return "done"

    collected = []
    result = handle(body, {
        Emit: lambda v, resume: (collected.append(v), resume(None))[1]
    })
    assert result == "done"
    assert collected == ["a", "b", "c"]


def test_nondeterminism():
    """Multi-shot continuations: resume called multiple times."""
    Choose = Effect("Choose")

    def body():
        x = perform(Choose, [1, 2])
        y = perform(Choose, [10, 20])
        return x + y

    def handler(choices, resume):
        results = []
        for c in choices:
            r = resume(c)
            if isinstance(r, list):
                results.extend(r)
            else:
                results.append(r)
        return results

    result = handle(body, {Choose: handler})
    assert sorted(result) == [11, 12, 21, 22]


def test_effect_identity():
    """Two Effect instances with the same name are distinct effects."""
    E1 = Effect("E")
    E2 = Effect("E")

    def body():
        a = perform(E1, "e1")
        b = perform(E2, "e2")
        return (a, b)

    result = handle(
        lambda: handle(body, {E1: lambda a, r: r(f"h1:{a}")}),
        {E2: lambda a, r: r(f"h2:{a}")}
    )
    assert result == ("h1:e1", "h2:e2")


def test_resume_not_called_with_nested():
    """Handler that doesn't resume short-circuits nested effects."""
    A = Effect("A")
    B = Effect("B")

    def body():
        x = perform(A, 1)
        y = perform(B, 2)
        return x + y

    result = handle(
        lambda: handle(body, {A: lambda v, resume: resume(v * 10)}),
        {B: lambda v, resume: "short-circuit"}
    )
    assert result == "short-circuit"
