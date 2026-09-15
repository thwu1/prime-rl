"""
Algebraic effect handler library with multi-shot delimited continuations.

Implements Koka-style ctl operation semantics using continuation-passing style
(CPS) for correct handler composition. Effects are functions that take a
continuation k and invoke it zero times (failure), once (tail-resumptive),
or multiple times (non-deterministic multi-shot resume). Handler composition
order determines whether state is shared or local across branches.

Also provides a replay-based generator interface for simpler computations
that do not require handler composition (e.g., pure Choose/Fail backtracking).
"""


# ─── Effect types ────────────────────────────────────────────────────

class Effect:
    """Base class for algebraic effect operations."""
    pass


class Choose(Effect):
    """
    Non-deterministic choice from a list of alternatives.
    Multi-shot: the continuation is resumed once per option.
    """
    def __init__(self, options):
        self.options = list(options)


class Fail(Effect):
    """
    Backtracking failure — abandon branch (zero-shot, no resume).
    """
    pass


class Get(Effect):
    """Read the current state value."""
    pass


class Set(Effect):
    """Write a new state value."""
    def __init__(self, value):
        self.value = value


class Ask(Effect):
    """Reader effect: get a contextual constant value."""
    pass


class Emit(Effect):
    """Writer effect: emit a message string."""
    def __init__(self, msg):
        self.msg = msg


# ─── CPS handler primitives ─────────────────────────────────────────
#
# In CPS, a computation is a function f(k) that calls continuation k
# with its result. Multi-shot resume = calling k multiple times.
# Handler composition is natural: nesting CPS handlers determines
# shared-vs-local state semantics automatically.

def choose(options, k):
    """
    Multi-shot resume: invoke continuation k for each option,
    collecting all result branches in depth-first lexicographic order.
    Corresponds to Koka's: ctl choice() resume(False) ++ resume(True)
    """
    results = []
    for opt in options:
        branch_result = k(opt)
        if isinstance(branch_result, list):
            results.extend(branch_result)
        else:
            results.append(branch_result)
    return results


def fail():
    """
    Zero-shot abandon: return empty list (no resume of continuation).
    """
    return []


def get_state(state_ref, k):
    """
    State get: read from shared mutable state cell, resume with value.
    state_ref is a single-element list [value] for mutability.
    """
    return k(state_ref[0])


def set_state(state_ref, value, k):
    """
    State set: write to shared mutable state cell, resume with None.
    """
    state_ref[0] = value
    return k(None)


def ask_reader(reader_value, k):
    """
    Reader ask: return the constant reader value, resume.
    """
    return k(reader_value)


# ─── Replay-based generator handler ─────────────────────────────────
#
# For pure Choose/Fail computations (no state composition needed),
# generators with replay-based multi-shot exploration are convenient.

def find_all(gen_func, *args, **kwargs):
    """
    Multi-shot handler using replay-based DFS exploration.

    Computations are generator functions yielding Choose/Fail effects.
    Each branch is explored by replaying the generator from scratch
    with recorded choices, guaranteeing branch isolation.

    Returns list of all successful results in lexicographic order.
    """
    results = []
    stack = [[]]

    while stack:
        choices = stack.pop()
        gen = gen_func(*args, **kwargs)
        replay_idx = 0
        done = False

        try:
            effect = next(gen)
        except StopIteration as e:
            results.append(e.value)
            continue

        while not done:
            if isinstance(effect, Choose):
                if replay_idx < len(choices):
                    try:
                        effect = gen.send(choices[replay_idx])
                        replay_idx += 1
                    except StopIteration as e:
                        results.append(e.value)
                        done = True
                else:
                    for opt in reversed(effect.options):
                        stack.append(choices + [opt])
                    done = True

            elif isinstance(effect, Fail):
                done = True

            else:
                raise TypeError(
                    f"Unknown effect: {type(effect).__name__}"
                )

    return results
