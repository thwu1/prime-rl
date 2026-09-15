#!/usr/bin/env python3
"""
Linearizability checker — reference solution.

Implements a DFS-based Wing-Gong style linearizability check for
concurrent histories on a read/write register.
"""
import sys
sys.path.insert(0, "/app")

from itertools import combinations
from typing import List, Set, Tuple, Any
from history import History, Operation


def is_linearizable(history: History) -> bool:
    """Check whether *history* is linearizable w.r.t. a read/write register."""
    completed = [op for op in history.operations if op.response_time is not None]
    crashed = [op for op in history.operations if op.response_time is None]

    # Try every subset of crashed operations (include / exclude each).
    for r in range(len(crashed) + 1):
        for subset in combinations(crashed, r):
            ops = completed + list(subset)
            if _check_linearizable(ops, history.initial_value):
                return True
    return False


def _check_linearizable(ops: List[Operation], init: int) -> bool:
    if not ops:
        return True
    all_ids = {op.op_id for op in ops}
    return _dfs(ops, init, set(), all_ids)


def _dfs(ops: List[Operation], state: int,
         linearized: Set[int], all_ids: Set[int]) -> bool:
    if linearized == all_ids:
        return True

    for op in ops:
        if op.op_id in linearized:
            continue

        # Real-time check: every un-linearized predecessor must already
        # be linearized.  A precedes B iff A.response_time < B.invoke_time.
        can_go = True
        for other in ops:
            if other.op_id in linearized or other.op_id == op.op_id:
                continue
            other_resp = (other.response_time
                          if other.response_time is not None
                          else float("inf"))
            if other_resp < op.invoke_time:
                can_go = False
                break
        if not can_go:
            continue

        new_state, matches = _apply(op, state)
        if matches:
            linearized.add(op.op_id)
            if _dfs(ops, new_state, linearized, all_ids):
                return True
            linearized.remove(op.op_id)

    return False


def _apply(op: Operation, state: int) -> Tuple[int, bool]:
    if op.op_type == "write":
        return op.arg, (op.response_value is None or op.response_value == "ok")
    if op.op_type == "read":
        if op.response_value is None:
            return state, True
        return state, op.response_value == state
    raise ValueError(f"unknown op_type: {op.op_type}")


# --------------- main: write checker.py into /app/ -----------------
if __name__ == "__main__":
    import inspect, textwrap

    src = textwrap.dedent('''\
    """Linearizability checker for concurrent operation histories."""
    from itertools import combinations
    from typing import List, Set, Tuple
    from history import History, Operation


    def is_linearizable(history: History) -> bool:
        completed = [op for op in history.operations if op.response_time is not None]
        crashed = [op for op in history.operations if op.response_time is None]
        for r in range(len(crashed) + 1):
            for subset in combinations(crashed, r):
                ops = completed + list(subset)
                if _check(ops, history.initial_value):
                    return True
        return False


    def _check(ops: List[Operation], init: int) -> bool:
        if not ops:
            return True
        return _dfs(ops, init, set(), {o.op_id for o in ops})


    def _dfs(ops, state, done, all_ids):
        if done == all_ids:
            return True
        for op in ops:
            if op.op_id in done:
                continue
            ok = True
            for o2 in ops:
                if o2.op_id in done or o2.op_id == op.op_id:
                    continue
                rt = o2.response_time if o2.response_time is not None else float("inf")
                if rt < op.invoke_time:
                    ok = False
                    break
            if not ok:
                continue
            ns, m = _apply(op, state)
            if m:
                done.add(op.op_id)
                if _dfs(ops, ns, done, all_ids):
                    return True
                done.remove(op.op_id)
        return False


    def _apply(op, state):
        if op.op_type == "write":
            return op.arg, (op.response_value is None or op.response_value == "ok")
        if op.op_type == "read":
            if op.response_value is None:
                return state, True
            return state, op.response_value == state
        raise ValueError(op.op_type)
    ''')

    with open("/app/checker.py", "w") as f:
        f.write(src)
    print("Wrote /app/checker.py")
