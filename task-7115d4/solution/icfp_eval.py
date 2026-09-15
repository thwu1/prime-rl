#!/usr/bin/env python3
"""
ICFP 2024 Language Evaluator Pipeline.

1. Extracts expressions from SQLite corpus database (active courses only).
2. Decodes binary-encoded expressions using the compiled C decoder.
3. Parses and evaluates ICFP expressions with call-by-name semantics.
4. For efficiency expressions exceeding the beta-reduction limit,
   detects Y-combinator patterns and translates to memoized Python.
5. Writes results to /app/results.json.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile

sys.setrecursionlimit(200000)

# ---------------------------------------------------------------------------
# Character mapping: index 0..93 -> human-readable character
# ---------------------------------------------------------------------------
ICFP_CHARS = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`|~ \n"
)
assert len(ICFP_CHARS) == 94, f"Expected 94 chars, got {len(ICFP_CHARS)}"

HUMAN_TO_IDX = {ch: i for i, ch in enumerate(ICFP_CHARS)}


def decode_string(body):
    """Decode an ICFP string-token body into a human-readable string."""
    return "".join(ICFP_CHARS[ord(c) - 33] for c in body)


def encode_string(s):
    """Encode a human-readable string into an ICFP string-token body."""
    return "".join(chr(HUMAN_TO_IDX[c] + 33) for c in s)


def decode_int(body):
    """Decode an ICFP integer-token body (base-94) into a Python int."""
    n = 0
    for c in body:
        n = n * 94 + (ord(c) - 33)
    return n


def encode_int_body(n):
    """Encode a non-negative Python int into an ICFP integer-token body."""
    if n == 0:
        return chr(33)
    digits = []
    while n > 0:
        digits.append(chr(n % 94 + 33))
        n //= 94
    return "".join(reversed(digits))


def trunc_div(a, b):
    """Integer division truncated towards zero."""
    q, r = divmod(a, b)
    if r != 0 and (a < 0) != (b < 0):
        q += 1
    return q


def trunc_mod(a, b):
    """Integer modulo consistent with trunc_div."""
    return a - trunc_div(a, b) * b


# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------
class IntLit:
    __slots__ = ("value",)
    def __init__(self, v): self.value = v
    def __repr__(self): return f"Int({self.value})"

class StrLit:
    __slots__ = ("value",)
    def __init__(self, v): self.value = v
    def __repr__(self): return f"Str({self.value!r})"

class BoolLit:
    __slots__ = ("value",)
    def __init__(self, v): self.value = v
    def __repr__(self): return f"Bool({self.value})"

class UnaryOp:
    __slots__ = ("op", "arg")
    def __init__(self, op, arg): self.op = op; self.arg = arg

class BinaryOp:
    __slots__ = ("op", "left", "right")
    def __init__(self, op, l, r): self.op = op; self.left = l; self.right = r

class IfExpr:
    __slots__ = ("cond", "then_e", "else_e")
    def __init__(self, c, t, e): self.cond = c; self.then_e = t; self.else_e = e

class Lambda:
    __slots__ = ("var", "body")
    def __init__(self, v, b): self.var = v; self.body = b

class Var:
    __slots__ = ("var",)
    def __init__(self, v): self.var = v

class Closure:
    __slots__ = ("var", "body", "env")
    def __init__(self, v, b, e): self.var = v; self.body = b; self.env = e


# ---------------------------------------------------------------------------
# Tokenizer & Parser
# ---------------------------------------------------------------------------
def tokenize(s):
    return s.strip().split()


def parse(tokens, pos=0):
    if pos >= len(tokens):
        raise ValueError("Unexpected end of input")
    tok = tokens[pos]
    ind, body = tok[0], tok[1:]

    if ind == "T":
        return BoolLit(True), pos + 1
    if ind == "F":
        return BoolLit(False), pos + 1
    if ind == "I":
        return IntLit(decode_int(body)), pos + 1
    if ind == "S":
        return StrLit(decode_string(body)), pos + 1
    if ind == "U":
        arg, np = parse(tokens, pos + 1)
        return UnaryOp(body, arg), np
    if ind == "B":
        left, np = parse(tokens, pos + 1)
        right, np = parse(tokens, np)
        return BinaryOp(body, left, right), np
    if ind == "?":
        c, np = parse(tokens, pos + 1)
        t, np = parse(tokens, np)
        e, np = parse(tokens, np)
        return IfExpr(c, t, e), np
    if ind == "L":
        var_num = decode_int(body)
        b, np = parse(tokens, pos + 1)
        return Lambda(var_num, b), np
    if ind == "v":
        return Var(decode_int(body)), pos + 1

    raise ValueError(f"Unknown indicator: {ind!r} in token {tok!r}")


# ---------------------------------------------------------------------------
# Call-by-name evaluator (environment-based, thunks)
# ---------------------------------------------------------------------------
class StepLimitExceeded(Exception):
    pass


class EvalError(Exception):
    pass


def evaluate(expr, env, steps_ref, limit=100_000):
    """Evaluate *expr* under *env* with call-by-name semantics."""
    while True:
        if isinstance(expr, (IntLit, StrLit, BoolLit)):
            return expr
        if isinstance(expr, Var):
            if expr.var not in env:
                raise EvalError(f"Unbound variable v{expr.var}")
            thunk_expr, thunk_env = env[expr.var]
            expr, env = thunk_expr, thunk_env
            continue
        if isinstance(expr, Lambda):
            return Closure(expr.var, expr.body, env)
        if isinstance(expr, UnaryOp):
            arg = evaluate(expr.arg, env, steps_ref, limit)
            return _eval_unary(expr.op, arg)
        if isinstance(expr, BinaryOp):
            if expr.op == "$":
                steps_ref[0] += 1
                if steps_ref[0] > limit:
                    raise StepLimitExceeded()
                func = evaluate(expr.left, env, steps_ref, limit)
                if not isinstance(func, Closure):
                    raise EvalError(f"Cannot apply non-closure: {type(func)}")
                new_env = dict(func.env)
                new_env[func.var] = (expr.right, env)
                expr, env = func.body, new_env
                continue
            left = evaluate(expr.left, env, steps_ref, limit)
            right = evaluate(expr.right, env, steps_ref, limit)
            return _eval_binary(expr.op, left, right)
        if isinstance(expr, IfExpr):
            cond = evaluate(expr.cond, env, steps_ref, limit)
            if not isinstance(cond, BoolLit):
                raise EvalError("Condition is not boolean")
            expr = expr.then_e if cond.value else expr.else_e
            continue
        raise EvalError(f"Unknown node type: {type(expr)}")


def _eval_unary(op, arg):
    if op == "-" and isinstance(arg, IntLit):
        return IntLit(-arg.value)
    if op == "!" and isinstance(arg, BoolLit):
        return BoolLit(not arg.value)
    if op == "#" and isinstance(arg, StrLit):
        encoded = encode_string(arg.value)
        return IntLit(decode_int(encoded))
    if op == "$" and isinstance(arg, IntLit):
        body = encode_int_body(arg.value)
        return StrLit(decode_string(body))
    raise EvalError(f"Bad unary {op!r} on {type(arg).__name__}")


def _eval_binary(op, left, right):
    if op == "+":
        return IntLit(left.value + right.value)
    if op == "-":
        return IntLit(left.value - right.value)
    if op == "*":
        return IntLit(left.value * right.value)
    if op == "/":
        return IntLit(trunc_div(left.value, right.value))
    if op == "%":
        return IntLit(trunc_mod(left.value, right.value))
    if op == "<":
        return BoolLit(left.value < right.value)
    if op == ">":
        return BoolLit(left.value > right.value)
    if op == "=":
        return BoolLit(left.value == right.value)
    if op == "|":
        return BoolLit(left.value or right.value)
    if op == "&":
        return BoolLit(left.value and right.value)
    if op == ".":
        return StrLit(left.value + right.value)
    if op == "T":
        return StrLit(right.value[: left.value])
    if op == "D":
        return StrLit(right.value[left.value :])
    raise EvalError(f"Bad binary {op!r}")


# ---------------------------------------------------------------------------
# Y-combinator detection & translation to memoised Python
# ---------------------------------------------------------------------------
def _is_y_combinator(node):
    """Return True if node matches lambda g. (lambda x. g(x x))(lambda x. g(x x))."""
    if not isinstance(node, Lambda):
        return False
    g = node.var
    b = node.body
    if not (isinstance(b, BinaryOp) and b.op == "$"):
        return False
    for arm in (b.left, b.right):
        if not isinstance(arm, Lambda):
            return False
        x = arm.var
        ab = arm.body
        if not (isinstance(ab, BinaryOp) and ab.op == "$"):
            return False
        if not (isinstance(ab.left, Var) and ab.left.var == g):
            return False
        inner = ab.right
        if not (isinstance(inner, BinaryOp) and inner.op == "$"):
            return False
        if not (isinstance(inner.left, Var) and inner.left.var == x):
            return False
        if not (isinstance(inner.right, Var) and inner.right.var == x):
            return False
    return True


def _detect_y_app(ast):
    """If ast is Y(f)(a1)(a2)... return (f_node, [a1, a2, ...])."""
    apps = []
    node = ast
    while isinstance(node, BinaryOp) and node.op == "$":
        apps.append(node.right)
        node = node.left
    if _is_y_combinator(node) and apps:
        func = apps[-1]
        args = list(reversed(apps[:-1]))
        return func, args
    return None


def _ast_to_py(expr, rec_var, actual_params):
    """Translate an ICFP AST body into a Python expression string."""
    if isinstance(expr, IntLit):
        return repr(expr.value)
    if isinstance(expr, StrLit):
        return repr(expr.value)
    if isinstance(expr, BoolLit):
        return "True" if expr.value else "False"
    if isinstance(expr, Var):
        if expr.var == rec_var:
            return "_f"
        for i, pv in enumerate(actual_params):
            if expr.var == pv:
                return f"_p{i}"
        return f"_v{expr.var}"
    if isinstance(expr, BinaryOp):
        if expr.op == "$":
            chain_args = []
            n = expr
            while isinstance(n, BinaryOp) and n.op == "$":
                chain_args.append(n.right)
                n = n.left
            chain_args.reverse()
            if isinstance(n, Var) and n.var == rec_var:
                parts = [_ast_to_py(a, rec_var, actual_params) for a in chain_args]
                return f"_f({', '.join(parts)})"
            result = _ast_to_py(n, rec_var, actual_params)
            for a in chain_args:
                result = f"({result})({_ast_to_py(a, rec_var, actual_params)})"
            return result
        l = _ast_to_py(expr.left, rec_var, actual_params)
        r = _ast_to_py(expr.right, rec_var, actual_params)
        if expr.op == "+": return f"({l}+{r})"
        if expr.op == "-": return f"({l}-{r})"
        if expr.op == "*": return f"({l}*{r})"
        if expr.op == "/": return f"_tdiv({l},{r})"
        if expr.op == "%": return f"_tmod({l},{r})"
        if expr.op == "<": return f"({l}<{r})"
        if expr.op == ">": return f"({l}>{r})"
        if expr.op == "=": return f"({l}=={r})"
        if expr.op == "|": return f"({l} or {r})"
        if expr.op == "&": return f"({l} and {r})"
        if expr.op == ".": return f"({l}+{r})"
        if expr.op == "T": return f"({r})[:{l}]"
        if expr.op == "D": return f"({r})[{l}:]"
    if isinstance(expr, IfExpr):
        c = _ast_to_py(expr.cond, rec_var, actual_params)
        t = _ast_to_py(expr.then_e, rec_var, actual_params)
        e = _ast_to_py(expr.else_e, rec_var, actual_params)
        return f"({t} if {c} else {e})"
    if isinstance(expr, UnaryOp):
        a = _ast_to_py(expr.arg, rec_var, actual_params)
        if expr.op == "-": return f"(-({a}))"
        if expr.op == "!": return f"(not ({a}))"
    return "None"


def analyze_and_compute(ast):
    """Try to recognise Y(f)(args) and compute via memoised Python."""
    res = _detect_y_app(ast)
    if res is None:
        return None
    func_node, arg_nodes = res

    params = []
    body = func_node
    while isinstance(body, Lambda):
        params.append(body.var)
        body = body.body
    if len(params) < 2:
        return None
    rec_var = params[0]
    actual_params = params[1:]

    arg_vals = []
    for an in arg_nodes:
        v = evaluate(an, {}, [0])
        if isinstance(v, IntLit):
            arg_vals.append(v.value)
        elif isinstance(v, StrLit):
            arg_vals.append(v.value)
        elif isinstance(v, BoolLit):
            arg_vals.append(v.value)
        else:
            return None

    py_body = _ast_to_py(body, rec_var, actual_params)
    p_names = ", ".join(f"_p{i}" for i in range(len(actual_params)))
    a_str = ", ".join(repr(v) for v in arg_vals)

    code = (
        "from functools import lru_cache\n"
        "def _tdiv(a,b):\n"
        "    q,r=divmod(a,b)\n"
        "    if r and (a<0)!=(b<0): q+=1\n"
        "    return q\n"
        "def _tmod(a,b): return a-_tdiv(a,b)*b\n"
        "@lru_cache(maxsize=None)\n"
        f"def _f({p_names}):\n"
        f"    return {py_body}\n"
        f"_result = _f({a_str})\n"
    )
    ns = {}
    exec(code, ns)
    return ns["_result"]


# ---------------------------------------------------------------------------
# Database extraction
# ---------------------------------------------------------------------------
def extract_expressions_from_db():
    """Extract all active expressions from the SQLite corpus database."""
    db_path = "/app/corpus.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT e.expr_id, e.encoding, e.content_text, e.content_blob
        FROM expressions e
        JOIN courses c ON e.course_id = c.course_id
        WHERE c.is_active = 1
        ORDER BY e.expr_id
    """)

    expressions = {}
    for row in cur.fetchall():
        eid = row['expr_id']
        if row['encoding'] == 'plaintext':
            expressions[eid] = row['content_text']
        elif row['encoding'] == 'icfpbin_v1':
            blob = row['content_blob']
            with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
                tmp.write(blob)
                tmp_path = tmp.name
            try:
                result = subprocess.run(
                    ['/app/tools/decoder', tmp_path],
                    capture_output=True, text=True, check=True
                )
                expressions[eid] = result.stdout.strip()
            finally:
                os.unlink(tmp_path)
        else:
            print(f"WARNING: Unknown encoding {row['encoding']} for {eid}",
                  file=sys.stderr)

    conn.close()
    return expressions


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------
def format_result(val):
    if isinstance(val, IntLit):
        return str(val.value)
    if isinstance(val, StrLit):
        return val.value
    if isinstance(val, BoolLit):
        return "true" if val.value else "false"
    return str(val)


def eval_expression(expr_str):
    tokens = tokenize(expr_str)
    ast, end = parse(tokens)
    if end != len(tokens):
        raise EvalError(f"Trailing tokens at position {end}")

    try:
        result = evaluate(ast, {}, [0])
        return format_result(result)
    except StepLimitExceeded:
        pass

    computed = analyze_and_compute(ast)
    if computed is not None:
        return str(computed)

    raise EvalError("Expression exceeded step limit and analysis failed")


def main():
    print("Extracting expressions from corpus database...")
    exprs = extract_expressions_from_db()
    print(f"Found {len(exprs)} active expressions")

    results = {}
    for eid in sorted(exprs.keys()):
        expr_str = exprs[eid]
        try:
            val = eval_expression(expr_str)
            results[eid] = val
            print(f"{eid}: {val}")
        except Exception as exc:
            print(f"{eid}: ERROR - {exc}", file=sys.stderr)
            results[eid] = f"ERROR: {exc}"

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {len(results)} results to /app/results.json")


if __name__ == "__main__":
    main()
