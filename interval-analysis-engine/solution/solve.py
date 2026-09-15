#!/usr/bin/env python3
"""
Value-range analysis -- reference solution.

"""

import json
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, "/app")
from ir_parser import parse_file

INF = float("inf")
NEG_INF = float("-inf")

MAX_WIDEN_ITER = 100
MAX_NARROW_ITER = 20


# -- Interval arithmetic -----------------------------------------------------

class Interval:
    __slots__ = ("lo", "hi")

    def __init__(self, lo, hi):
        self.lo = lo
        self.hi = hi

    def __eq__(self, other):
        if not isinstance(other, Interval):
            return False
        return self.lo == other.lo and self.hi == other.hi

    def __hash__(self):
        return hash((self.lo, self.hi))

    def __repr__(self):
        l = "-inf" if self.lo == NEG_INF else str(self.lo)
        h = "inf" if self.hi == INF else str(self.hi)
        return f"[{l}, {h}]"


def iv_const(c):
    return Interval(c, c)


def iv_join(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return Interval(min(a.lo, b.lo), max(a.hi, b.hi))


def iv_meet(a, b):
    if a is None or b is None:
        return None
    lo = max(a.lo, b.lo)
    hi = min(a.hi, b.hi)
    if lo > hi:
        return None
    return Interval(lo, hi)


def iv_widen(old, new):
    if old is None:
        return new
    if new is None:
        return old
    lo = old.lo if new.lo >= old.lo else NEG_INF
    hi = old.hi if new.hi <= old.hi else INF
    return Interval(lo, hi)


def iv_narrow(old, new):
    if old is None:
        return None
    if new is None:
        return old
    lo = new.lo if old.lo == NEG_INF else old.lo
    hi = new.hi if old.hi == INF else old.hi
    return Interval(lo, hi)


def _mul_bound(x, y):
    if x == 0 or y == 0:
        return 0
    if x == INF:
        return INF if y > 0 else NEG_INF
    if x == NEG_INF:
        return NEG_INF if y > 0 else INF
    if y == INF:
        return INF if x > 0 else NEG_INF
    if y == NEG_INF:
        return NEG_INF if x > 0 else INF
    return x * y


def iv_add(a, b):
    if a is None or b is None:
        return None
    return Interval(a.lo + b.lo, a.hi + b.hi)


def iv_sub(a, b):
    if a is None or b is None:
        return None
    return Interval(a.lo - b.hi, a.hi - b.lo)


def iv_mul(a, b):
    if a is None or b is None:
        return None
    corners = [
        _mul_bound(a.lo, b.lo),
        _mul_bound(a.lo, b.hi),
        _mul_bound(a.hi, b.lo),
        _mul_bound(a.hi, b.hi),
    ]
    return Interval(min(corners), max(corners))


# -- Abstract state helpers ---------------------------------------------------

def state_join(s1, s2):
    if s1 is None:
        return s2
    if s2 is None:
        return s1
    result = {}
    for v in set(s1) | set(s2):
        result[v] = iv_join(s1.get(v), s2.get(v))
    return result


def state_widen(old, new):
    if old is None:
        return new
    if new is None:
        return old
    result = {}
    for v in set(old) | set(new):
        result[v] = iv_widen(old.get(v), new.get(v))
    return result


def state_narrow(old, new):
    if old is None:
        return None
    if new is None:
        return old
    result = {}
    for v in set(old) | set(new):
        result[v] = iv_narrow(old.get(v), new.get(v))
    return result


def state_equal(s1, s2):
    if s1 is None and s2 is None:
        return True
    if s1 is None or s2 is None:
        return False
    keys = set(s1) | set(s2)
    for v in keys:
        a, b = s1.get(v), s2.get(v)
        if a is None and b is None:
            continue
        if a is None or b is None:
            return False
        if a != b:
            return False
    return True


# -- Condition refinement -----------------------------------------------------

def _rhs_interval(state, rhs):
    if rhs["type"] == "const":
        return iv_const(rhs["value"])
    return state.get(rhs["name"])


def _true_constraint(op, rhs_iv):
    if op == "<":
        hi = rhs_iv.hi - 1 if rhs_iv.hi != INF else INF
        return Interval(NEG_INF, hi)
    if op == "<=":
        return Interval(NEG_INF, rhs_iv.hi)
    if op == ">":
        lo = rhs_iv.lo + 1 if rhs_iv.lo != NEG_INF else NEG_INF
        return Interval(lo, INF)
    if op == ">=":
        return Interval(rhs_iv.lo, INF)
    if op == "==":
        return Interval(rhs_iv.lo, rhs_iv.hi)
    return Interval(NEG_INF, INF)


def _false_constraint(op, rhs_iv):
    if op == "<":
        return Interval(rhs_iv.lo, INF)
    if op == "<=":
        lo = rhs_iv.lo + 1 if rhs_iv.lo != NEG_INF else NEG_INF
        return Interval(lo, INF)
    if op == ">":
        return Interval(NEG_INF, rhs_iv.hi)
    if op == ">=":
        hi = rhs_iv.hi - 1 if rhs_iv.hi != INF else INF
        return Interval(NEG_INF, hi)
    if op == "==":
        return Interval(NEG_INF, INF)
    if op == "!=":
        return Interval(rhs_iv.lo, rhs_iv.hi)
    return Interval(NEG_INF, INF)


def refine_condition(state, cond, is_true):
    if state is None:
        return None
    left_var = cond["left"]
    left_iv = state.get(left_var)
    rhs_iv = _rhs_interval(state, cond["right"])
    if left_iv is None or rhs_iv is None:
        return None
    constraint = _true_constraint(cond["op"], rhs_iv) if is_true else _false_constraint(cond["op"], rhs_iv)
    refined = iv_meet(left_iv, constraint)
    if refined is None:
        return None
    new_state = dict(state)
    new_state[left_var] = refined
    return new_state


# -- Analyzer -----------------------------------------------------------------

class Analyzer:
    def __init__(self, program):
        self.program = program
        self.call_cache = {}

    def analyze_main(self):
        exit_state, _ = self._analyze_function("main", [], ())
        return exit_state

    def _analyze_function(self, func_name, arg_intervals, ctx):
        func = self.program["functions"][func_name]
        state = {}
        for param, iv in zip(func["params"], arg_intervals):
            state[param] = iv
        return_vals = []
        exit_state = self._stmts(func["body"], state, ctx, func_name, return_vals)
        merged_state = exit_state
        ret_iv = None
        for rstate, rval in return_vals:
            merged_state = state_join(merged_state, rstate)
            ret_iv = iv_join(ret_iv, rval)
        return merged_state, ret_iv

    def _stmts(self, stmts, state, ctx, fn, rvs):
        for s in stmts:
            if state is None:
                return None
            state = self._stmt(s, state, ctx, fn, rvs)
        return state

    def _stmt(self, s, state, ctx, fn, rvs):
        if state is None:
            return None
        t = s["type"]
        if t == "assign":
            return self._assign(s, state, ctx, fn)
        if t == "if":
            return self._if(s, state, ctx, fn, rvs)
        if t == "while":
            return self._while(s, state, ctx, fn, rvs)
        if t == "return":
            return self._return(s, state, rvs)
        raise ValueError(f"unknown stmt type {t}")

    def _assign(self, s, state, ctx, fn):
        val = self._expr(s["expr"], state, ctx, fn, s.get("line", 0))
        ns = dict(state)
        ns[s["target"]] = val
        return ns

    def _expr(self, e, state, ctx, fn, line):
        t = e["type"]
        if t == "const":
            return iv_const(e["value"])
        if t == "var":
            return state.get(e["name"])
        if t == "binop":
            left = state.get(e["left"])
            right = state.get(e["right"])
            if left is None or right is None:
                return None
            op = e["op"]
            if op == "+":
                return iv_add(left, right)
            if op == "-":
                return iv_sub(left, right)
            if op == "*":
                return iv_mul(left, right)
            raise ValueError(f"unknown op {op}")
        if t == "call":
            return self._call(e, state, ctx, fn, line)
        raise ValueError(f"unknown expr type {t}")

    def _call(self, e, state, ctx, fn, line):
        callee = e["func"]
        arg_ivs = [state.get(a) for a in e["args"]]
        new_ctx = (f"{fn}:{line}",)
        arg_key = tuple((iv.lo, iv.hi) if iv else None for iv in arg_ivs)
        cache_key = (callee, new_ctx, arg_key)
        if cache_key in self.call_cache:
            return self.call_cache[cache_key]
        self.call_cache[cache_key] = None
        _, ret_iv = self._analyze_function(callee, arg_ivs, new_ctx)
        self.call_cache[cache_key] = ret_iv
        return ret_iv

    def _if(self, s, state, ctx, fn, rvs):
        cond = s["cond"]
        ts = refine_condition(state, cond, True)
        fs = refine_condition(state, cond, False)
        if ts is not None:
            ts = self._stmts(s["then_body"], ts, ctx, fn, rvs)
        if fs is not None:
            if s["else_body"]:
                fs = self._stmts(s["else_body"], fs, ctx, fn, rvs)
        return state_join(ts, fs)

    def _while(self, s, state, ctx, fn, rvs):
        cond = s["cond"]
        head = dict(state)

        for _ in range(MAX_WIDEN_ITER):
            ts = refine_condition(head, cond, True)
            if ts is None:
                break
            body_exit = self._stmts(s["body"], dict(ts), ctx, fn, rvs)
            if body_exit is None:
                break
            joined = state_join(state, body_exit)
            new_head = state_widen(head, joined)
            if state_equal(new_head, head):
                break
            head = new_head

        for _ in range(MAX_NARROW_ITER):
            ts = refine_condition(head, cond, True)
            if ts is None:
                break
            body_exit = self._stmts(s["body"], dict(ts), ctx, fn, rvs)
            if body_exit is None:
                break
            joined = state_join(state, body_exit)
            new_head = state_narrow(head, joined)
            if state_equal(new_head, head):
                break
            head = new_head

        return refine_condition(head, cond, False)

    def _return(self, s, state, rvs):
        rvs.append((state, state.get(s["var"])))
        return None


# -- Call graph generation ----------------------------------------------------

def _find_calls_in_stmts(stmts, func_name, edges):
    for s in stmts:
        if s["type"] == "assign":
            expr = s["expr"]
            if expr["type"] == "call":
                edges.add((func_name, expr["func"]))
        elif s["type"] == "if":
            _find_calls_in_stmts(s["then_body"], func_name, edges)
            _find_calls_in_stmts(s["else_body"], func_name, edges)
        elif s["type"] == "while":
            _find_calls_in_stmts(s["body"], func_name, edges)


def generate_call_graphs(programs_dir):
    os.makedirs("/app/graphs", exist_ok=True)
    for filename in sorted(os.listdir(programs_dir)):
        if not filename.endswith(".ir"):
            continue
        program = parse_file(os.path.join(programs_dir, filename))
        name = filename[:-3]

        edges = set()
        for func_name, func in program["functions"].items():
            _find_calls_in_stmts(func["body"], func_name, edges)

        dot_path = f"/app/graphs/{name}.dot"
        with open(dot_path, "w") as f:
            f.write("digraph call_graph {\n")
            for func_name in sorted(program["functions"]):
                f.write(f"    {func_name};\n")
            for caller, callee in sorted(edges):
                f.write(f"    {caller} -> {callee};\n")
            f.write("}\n")

        svg_path = f"/app/graphs/{name}.svg"
        subprocess.run(["dot", "-Tsvg", "-o", svg_path, dot_path], check=True)


# -- Output formatting --------------------------------------------------------

def format_interval(iv):
    if iv is None:
        return None
    lo = iv.lo if iv.lo != NEG_INF else "-inf"
    hi = iv.hi if iv.hi != INF else "inf"
    return [lo, hi]


def write_sqlite(results):
    db_path = "/app/analysis.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE results (
            program TEXT NOT NULL,
            variable TEXT NOT NULL,
            lo TEXT NOT NULL,
            hi TEXT NOT NULL,
            PRIMARY KEY (program, variable)
        )
    """)
    for program, vars_dict in results.items():
        for var, (lo, hi) in vars_dict.items():
            conn.execute(
                "INSERT INTO results (program, variable, lo, hi) VALUES (?, ?, ?, ?)",
                (program, var, str(lo), str(hi)),
            )
    conn.commit()
    conn.close()


def main():
    results = {}
    programs_dir = "/app/programs"
    for filename in sorted(os.listdir(programs_dir)):
        if not filename.endswith(".ir"):
            continue
        program = parse_file(os.path.join(programs_dir, filename))
        analyzer = Analyzer(program)
        exit_state = analyzer.analyze_main()
        prog_results = {}
        if exit_state:
            for var_name in sorted(exit_state):
                if var_name.startswith("__"):
                    continue
                fmt = format_interval(exit_state[var_name])
                if fmt is not None:
                    prog_results[var_name] = fmt
        results[filename] = prog_results

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    write_sqlite(results)
    generate_call_graphs(programs_dir)


if __name__ == "__main__":
    main()
