"""
Handler composition demonstrations using CPS-based algebraic effects.

Each function implements a specific handler composition scenario
matching the semantics defined by the oracle and Koka reference programs.
The nesting order of handlers determines whether state is shared (state
handler outside choice handler) or local (choice handler outside state
handler) across non-deterministic branches.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from effects import choose, fail, get_state, set_state, ask_reader


def _xor_cps(k):
    """CPS XOR computation: choice() XOR choice()."""
    return choose([False, True], lambda p:
        choose([False, True], lambda q:
            k((not q) if p else q)))


def choice_xor():
    """
    choice-all(xor) — multi-shot resume with boolean XOR.

    Explores all branches of choice() XOR choice() using
    resume(False) ++ resume(True) in DFS order.
    """
    return _xor_cps(lambda x: [x])


def state_choice():
    """
    pstate(0) { choice-all { surprising() } } — shared state.

    State handler is OUTSIDE choice handler, so all choice branches
    share a single mutable state cell. Mutations from earlier branches
    are visible to later branches.
    """
    state = [0]

    def surprising(k):
        return choose([False, True], lambda p:
            get_state(state, lambda i:
                set_state(state, i + 1, lambda _:
                    _xor_cps(k) if (i > 0 and p) else k(False))))

    results = surprising(lambda x: [x])
    return (results, state[0])


def choice_state():
    """
    choice-all { pstate(0) { surprising() } } — local state.

    Choice handler is OUTSIDE state handler, so each choice branch
    gets its own independent state initialized to 0.
    """
    def outer(k):
        return choose([False, True], lambda p:
            _surprising_local(p, k))

    def _surprising_local(p, k):
        state = [0]
        def cont(result):
            return k((result, state[0]))
        return get_state(state, lambda i:
            set_state(state, i + 1, lambda _:
                _xor_cps(cont) if (i > 0 and p) else cont(False)))

    return outer(lambda x: [x])


def compose_triple_shared():
    """
    reader(10) { pstate(0) { choice-all { triple() } } } — shared state.

    Three handlers composed: reader (constant), state (shared), choice.
    triple: r=ask(); p=choice(); s=get(); set(s+r); if p then s+r else s
    """
    reader_val = 10
    state = [0]

    def triple(k):
        return choose([False, True], lambda p:
            get_state(state, lambda s:
                set_state(state, s + reader_val, lambda _:
                    k(s + reader_val) if p else k(s))))

    results = triple(lambda x: [x])
    return (results, state[0])


def compose_triple_local():
    """
    reader(10) { choice-all { pstate(0) { triple() } } } — local state.

    Three handlers composed: reader (constant), choice, state (local per branch).
    """
    reader_val = 10

    def outer(k):
        return choose([False, True], lambda p:
            _triple_local(p, reader_val, k))

    def _triple_local(p, rv, k):
        state = [0]
        def cont(result):
            return k((result, state[0]))
        return get_state(state, lambda s:
            set_state(state, s + rv, lambda _:
                cont(s + rv) if p else cont(s)))

    return outer(lambda x: [x])
