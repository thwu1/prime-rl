#!/usr/bin/env python3
"""
Abstract interpreter using the interval domain with widening and narrowing.
Detects buffer overflows (boa), division by zero (dbz), and assertion violations.
"""

import json
import sys
import math

INF = float("inf")
NEG_INF = float("-inf")

MAX_WIDEN_ITERS = 200
MAX_NARROW_ITERS = 20


# ---------------------------------------------------------------------------
# Interval domain
# ---------------------------------------------------------------------------

class Interval:
    __slots__ = ("lo", "hi")

    def __init__(self, lo, hi):
        self.lo = lo
        self.hi = hi

    def is_bottom(self):
        return self.lo > self.hi

    @staticmethod
    def bottom():
        return Interval(1, 0)

    @staticmethod
    def top():
        return Interval(NEG_INF, INF)

    # -- lattice ops --

    def join(self, other):
        if self.is_bottom():
            return Interval(other.lo, other.hi)
        if other.is_bottom():
            return Interval(self.lo, self.hi)
        return Interval(min(self.lo, other.lo), max(self.hi, other.hi))

    def meet(self, other):
        return Interval(max(self.lo, other.lo), min(self.hi, other.hi))

    def widen(self, other):
        if self.is_bottom():
            return Interval(other.lo, other.hi)
        if other.is_bottom():
            return Interval(self.lo, self.hi)
        lo = self.lo if other.lo >= self.lo else NEG_INF
        hi = self.hi if other.hi <= self.hi else INF
        return Interval(lo, hi)

    def narrow(self, other):
        if self.is_bottom():
            return Interval(self.lo, self.hi)
        if other.is_bottom():
            return Interval(other.lo, other.hi)
        lo = other.lo if self.lo == NEG_INF else self.lo
        hi = other.hi if self.hi == INF else self.hi
        return Interval(lo, hi)

    # -- arithmetic --

    def add(self, other):
        return Interval(self.lo + other.lo, self.hi + other.hi)

    def sub(self, other):
        return Interval(self.lo - other.hi, self.hi - other.lo)

    def mul(self, other):
        def _m(a, b):
            if a == 0 or b == 0:
                return 0
            return a * b
        corners = [_m(a, b) for a in (self.lo, self.hi) for b in (other.lo, other.hi)]
        return Interval(min(corners), max(corners))

    @staticmethod
    def _safe_div(a, b):
        if a == 0:
            return 0
        if math.isinf(b):
            if math.isinf(a):
                return INF if (a > 0) == (b > 0) else NEG_INF
            return 0
        if math.isinf(a):
            return INF if (a > 0) == (b > 0) else NEG_INF
        if b == 0:
            return INF if a > 0 else NEG_INF
        return int(a / b)

    def _div_nonzero(self, other):
        corners = [Interval._safe_div(a, b)
                    for a in (self.lo, self.hi)
                    for b in (other.lo, other.hi)]
        return Interval(min(corners), max(corners))

    def div(self, other):
        if self.is_bottom() or other.is_bottom():
            return Interval.bottom()
        if other.lo > 0 or other.hi < 0:
            return self._div_nonzero(other)
        # other spans zero — split
        parts = []
        if other.lo < 0:
            parts.append(self._div_nonzero(Interval(other.lo, -1)))
        if other.hi > 0:
            parts.append(self._div_nonzero(Interval(1, other.hi)))
        if not parts:
            return Interval.top()
        r = parts[0]
        for p in parts[1:]:
            r = r.join(p)
        return r

    # -- queries --

    def contains_zero(self):
        return self.lo <= 0 <= self.hi

    def is_only_zero(self):
        return self.lo == 0 and self.hi == 0

    def __eq__(self, other):
        if self.is_bottom() and other.is_bottom():
            return True
        return self.lo == other.lo and self.hi == other.hi

    def __repr__(self):
        if self.is_bottom():
            return "bot"
        return f"[{self.lo}, {self.hi}]"


# ---------------------------------------------------------------------------
# Abstract state  (variable -> Interval)
# ---------------------------------------------------------------------------

class State:
    __slots__ = ("env", "_bot")

    def __init__(self, env=None, bot=False):
        self.env = dict(env) if env else {}
        self._bot = bot

    @staticmethod
    def bottom():
        return State(bot=True)

    def is_bottom(self):
        return self._bot

    def copy(self):
        return State(self.env, self._bot)

    def get(self, var):
        if self._bot:
            return Interval.bottom()
        return self.env.get(var, Interval.top())

    def set(self, var, itv):
        if self._bot:
            return self
        s = self.copy()
        s.env[var] = itv
        if itv.is_bottom():
            s._bot = True
        return s

    def join(self, other):
        if self._bot:
            return other.copy()
        if other._bot:
            return self.copy()
        keys = set(self.env) | set(other.env)
        return State({k: self.get(k).join(other.get(k)) for k in keys})

    def widen(self, other):
        if self._bot:
            return other.copy()
        if other._bot:
            return self.copy()
        keys = set(self.env) | set(other.env)
        return State({k: self.get(k).widen(other.get(k)) for k in keys})

    def narrow(self, other):
        if self._bot:
            return self.copy()
        if other._bot:
            return other.copy()
        keys = set(self.env) | set(other.env)
        return State({k: self.get(k).narrow(other.get(k)) for k in keys})

    def __eq__(self, other):
        if self._bot and other._bot:
            return True
        if self._bot or other._bot:
            return False
        keys = set(self.env) | set(other.env)
        return all(self.get(k) == other.get(k) for k in keys)


# ---------------------------------------------------------------------------
# Condition filtering  (refine state by assuming condition true / false)
# ---------------------------------------------------------------------------

def _filter_cmp(state, op, left_expr, right_expr, arrays):
    """Refine state assuming  left_expr  op  right_expr  is true."""
    left_val = _eval(left_expr, state, arrays, -1, [])
    right_val = _eval(right_expr, state, arrays, -1, [])
    if left_val.is_bottom() or right_val.is_bottom():
        return State.bottom()

    if op == "<":
        new_l = Interval(left_val.lo, min(left_val.hi, right_val.hi - 1))
        new_r = Interval(max(right_val.lo, left_val.lo + 1), right_val.hi)
    elif op == "<=":
        new_l = Interval(left_val.lo, min(left_val.hi, right_val.hi))
        new_r = Interval(max(right_val.lo, left_val.lo), right_val.hi)
    elif op == ">":
        new_l = Interval(max(left_val.lo, right_val.lo + 1), left_val.hi)
        new_r = Interval(right_val.lo, min(right_val.hi, left_val.hi - 1))
    elif op == ">=":
        new_l = Interval(max(left_val.lo, right_val.lo), left_val.hi)
        new_r = Interval(right_val.lo, min(right_val.hi, left_val.hi))
    elif op == "==":
        m = left_val.meet(right_val)
        new_l = m
        new_r = m
    elif op == "!=":
        new_l = left_val
        new_r = right_val
        if right_val.lo == right_val.hi:
            v = right_val.lo
            if left_val.lo == v and left_val.hi == v:
                return State.bottom()
            if left_val.lo == v:
                new_l = Interval(v + 1, left_val.hi)
            elif left_val.hi == v:
                new_l = Interval(left_val.lo, v - 1)
        elif left_val.lo == left_val.hi:
            v = left_val.lo
            if right_val.lo == v and right_val.hi == v:
                return State.bottom()
            if right_val.lo == v:
                new_r = Interval(v + 1, right_val.hi)
            elif right_val.hi == v:
                new_r = Interval(right_val.lo, v - 1)
    else:
        return state

    if new_l.is_bottom() or new_r.is_bottom():
        return State.bottom()

    s = state.copy()
    if left_expr.get("expr") == "var":
        refined = s.get(left_expr["name"]).meet(new_l)
        if refined.is_bottom():
            return State.bottom()
        s = s.set(left_expr["name"], refined)
    if right_expr.get("expr") == "var":
        refined = s.get(right_expr["name"]).meet(new_r)
        if refined.is_bottom():
            return State.bottom()
        s = s.set(right_expr["name"], refined)
    return s


_NEG_CMP = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}


def filter_true(state, cond, arrays):
    if state.is_bottom():
        return state
    kind = cond["expr"]
    if kind == "binop":
        op = cond["op"]
        if op in _NEG_CMP:
            return _filter_cmp(state, op, cond["left"], cond["right"], arrays)
        if op == "&&":
            return filter_true(filter_true(state, cond["left"], arrays),
                               cond["right"], arrays)
        if op == "||":
            return (filter_true(state, cond["left"], arrays)
                    .join(filter_true(state, cond["right"], arrays)))
    if kind == "unop" and cond["op"] == "!":
        return filter_false(state, cond["operand"], arrays)
    return state  # conservative


def filter_false(state, cond, arrays):
    if state.is_bottom():
        return state
    kind = cond["expr"]
    if kind == "binop":
        op = cond["op"]
        neg = _NEG_CMP.get(op)
        if neg:
            return _filter_cmp(state, neg, cond["left"], cond["right"], arrays)
        if op == "&&":
            return (filter_false(state, cond["left"], arrays)
                    .join(filter_false(state, cond["right"], arrays)))
        if op == "||":
            return filter_false(filter_false(state, cond["left"], arrays),
                                cond["right"], arrays)
    if kind == "unop" and cond["op"] == "!":
        return filter_true(state, cond["operand"], arrays)
    return state


# ---------------------------------------------------------------------------
# Expression evaluation
# ---------------------------------------------------------------------------

def _eval(expr, state, arrays, line, checks):
    """Evaluate *expr* in *state*, appending any discovered checks."""
    if state.is_bottom():
        return Interval.bottom()
    kind = expr["expr"]

    if kind == "const":
        v = expr["value"]
        return Interval(v, v)

    if kind == "var":
        return state.get(expr["name"])

    if kind == "nondet":
        return Interval.top()

    if kind == "array_read":
        idx = _eval(expr["index"], state, arrays, line, checks)
        if not idx.is_bottom() and line >= 0:
            size = arrays[expr["array"]]
            _check_boa(idx, size, line, checks)
        return Interval.top()

    if kind == "binop":
        op = expr["op"]
        lv = _eval(expr["left"], state, arrays, line, checks)
        rv = _eval(expr["right"], state, arrays, line, checks)
        if lv.is_bottom() or rv.is_bottom():
            return Interval.bottom()

        if op == "+": return lv.add(rv)
        if op == "-": return lv.sub(rv)
        if op == "*": return lv.mul(rv)
        if op in ("/", "%"):
            if line >= 0:
                _check_dbz(rv, line, checks)
            if op == "/":
                if rv.contains_zero() and rv.is_only_zero():
                    return Interval.top()
                return lv.div(rv)
            # modulo — conservative
            if rv.is_bottom() or rv.is_only_zero():
                return Interval.top()
            if rv.lo > 0:
                return Interval(-(rv.hi - 1), rv.hi - 1)
            if rv.hi < 0:
                return Interval(rv.lo + 1, -(rv.lo + 1))
            return Interval.top()

        # comparisons → 0 or 1
        return _eval_cmp(lv, rv, op)

    if kind == "unop":
        ov = _eval(expr["operand"], state, arrays, line, checks)
        if ov.is_bottom():
            return Interval.bottom()
        if expr["op"] == "-":
            return Interval(-ov.hi, -ov.lo)
        if expr["op"] == "!":
            if ov.lo > 0 or ov.hi < 0:
                return Interval(0, 0)
            if ov.is_only_zero():
                return Interval(1, 1)
            return Interval(0, 1)

    return Interval.top()


def _eval_cmp(lv, rv, op):
    if op == "<":
        if lv.hi < rv.lo: return Interval(1, 1)
        if lv.lo >= rv.hi: return Interval(0, 0)
    elif op == "<=":
        if lv.hi <= rv.lo: return Interval(1, 1)
        if lv.lo > rv.hi: return Interval(0, 0)
    elif op == ">":
        return _eval_cmp(rv, lv, "<")
    elif op == ">=":
        return _eval_cmp(rv, lv, "<=")
    elif op == "==":
        if lv.lo == lv.hi == rv.lo == rv.hi: return Interval(1, 1)
        if lv.hi < rv.lo or lv.lo > rv.hi: return Interval(0, 0)
    elif op == "!=":
        if lv.hi < rv.lo or lv.lo > rv.hi: return Interval(1, 1)
        if lv.lo == lv.hi == rv.lo == rv.hi: return Interval(0, 0)
    return Interval(0, 1)


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def _check_boa(idx, size, line, checks):
    valid = Interval(0, size - 1)
    if idx.lo >= valid.lo and idx.hi <= valid.hi:
        checks.append({"line": line, "kind": "boa", "status": "safe"})
    elif idx.lo > valid.hi or idx.hi < valid.lo:
        checks.append({"line": line, "kind": "boa", "status": "error"})
    else:
        checks.append({"line": line, "kind": "boa", "status": "warning"})


def _check_dbz(div_itv, line, checks):
    if not div_itv.contains_zero():
        checks.append({"line": line, "kind": "dbz", "status": "safe"})
    elif div_itv.is_only_zero():
        checks.append({"line": line, "kind": "dbz", "status": "error"})
    else:
        checks.append({"line": line, "kind": "dbz", "status": "warning"})


def _check_assert(cond, state, arrays, line, checks):
    if state.is_bottom():
        checks.append({"line": line, "kind": "assert", "status": "safe"})
        return
    ts = filter_true(state, cond, arrays)
    fs = filter_false(state, cond, arrays)
    if fs.is_bottom():
        checks.append({"line": line, "kind": "assert", "status": "safe"})
    elif ts.is_bottom():
        checks.append({"line": line, "kind": "assert", "status": "error"})
    else:
        checks.append({"line": line, "kind": "assert", "status": "warning"})


# ---------------------------------------------------------------------------
# Statement analysis
# ---------------------------------------------------------------------------

def _analyze_stmts(stmts, state, arrays, checks):
    for s in stmts:
        state = _analyze_stmt(s, state, arrays, checks)
    return state


def _analyze_stmt(stmt, state, arrays, checks):
    if state.is_bottom():
        return state
    kind = stmt["stmt"]
    line = stmt["line"]

    if kind == "assign":
        val = _eval(stmt["expr"], state, arrays, line, checks)
        return state.set(stmt["target"], val)

    if kind == "array_write":
        idx = _eval(stmt["index"], state, arrays, line, checks)
        _eval(stmt["value"], state, arrays, line, checks)
        size = arrays[stmt["array"]]
        _check_boa(idx, size, line, checks)
        return state

    if kind == "while":
        return _analyze_while(stmt, state, arrays, checks)

    if kind == "if":
        ts = filter_true(state, stmt["cond"], arrays)
        fs = filter_false(state, stmt["cond"], arrays)
        tc, fc = [], []
        te = _analyze_stmts(stmt["then_body"], ts, arrays, tc)
        if "else_body" in stmt and stmt["else_body"]:
            fe = _analyze_stmts(stmt["else_body"], fs, arrays, fc)
        else:
            fe = fs
        checks.extend(tc)
        checks.extend(fc)
        return te.join(fe)

    if kind == "assert":
        _check_assert(stmt["cond"], state, arrays, line, checks)
        return filter_true(state, stmt["cond"], arrays)

    return state


def _analyze_while(stmt, init, arrays, checks):
    cond = stmt["cond"]
    body = stmt["body"]

    # -- widening phase --
    head = init.copy()
    for _ in range(MAX_WIDEN_ITERS):
        prev = head
        inside = filter_true(head, cond, arrays)
        if inside.is_bottom():
            break
        after = _analyze_stmts(body, inside, arrays, [])
        joined = init.join(after)
        head = prev.widen(joined)
        if head == prev:
            break

    # -- narrowing phase --
    for _ in range(MAX_NARROW_ITERS):
        prev = head
        inside = filter_true(head, cond, arrays)
        if inside.is_bottom():
            break
        after = _analyze_stmts(body, inside, arrays, [])
        joined = init.join(after)
        head = prev.narrow(joined)
        if head == prev:
            break

    # -- final pass: collect checks inside the body --
    inside = filter_true(head, cond, arrays)
    if not inside.is_bottom():
        _analyze_stmts(body, inside, arrays, checks)

    return filter_false(head, cond, arrays)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(program):
    arrays = program.get("arrays", {})
    body = program["body"]
    state = State()
    checks = []
    _analyze_stmts(body, state, arrays, checks)
    checks.sort(key=lambda c: (c["line"], c["kind"]))
    return {"checks": checks}


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyzer.py <program.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        prog = json.load(f)
    result = analyze(prog)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
