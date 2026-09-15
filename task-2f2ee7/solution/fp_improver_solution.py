"""FPCore floating-point accuracy improver — full solution.

Parses FPCore S-expression format, evaluates in float64 and arbitrary
precision (mpmath), and provides algebraically rewritten versions of
6 benchmark expressions that eliminate catastrophic cancellation.
"""

import math
from mpmath import mp, mpf


# ============================================================
# AST node types
# ============================================================

class Num:
    """Numeric literal."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Num({self.value})"


class Var:
    """Variable reference."""
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Var({self.name})"


class Op:
    """Operator application."""
    def __init__(self, op, args):
        self.op = op
        self.args = args

    def __repr__(self):
        return f"Op({self.op}, {self.args})"


class If:
    """Conditional expression."""
    def __init__(self, cond, then_expr, else_expr):
        self.cond = cond
        self.then_expr = then_expr
        self.else_expr = else_expr


class Let:
    """Let binding expression."""
    def __init__(self, bindings, body):
        self.bindings = bindings  # list of (name_str, Expr)
        self.body = body


class FPCoreExpr:
    """A parsed FPCore expression with metadata."""
    def __init__(self, name, params, body, pre=None):
        self.name = name
        self.params = params
        self.body = body
        self.pre = pre


# ============================================================
# Tokenizer
# ============================================================

def _tokenize(text):
    """Tokenize S-expression text into a list of strings."""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\n\r":
            i += 1
        elif c == ";":
            # Line comment
            while i < n and text[i] != "\n":
                i += 1
        elif c in "()[]":
            tokens.append(c)
            i += 1
        elif c == '"':
            # String literal
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                j += 1
            tokens.append(text[i : j + 1])
            i = j + 1
        else:
            # Atom (symbol, number, keyword)
            j = i
            while j < n and text[j] not in ' \t\n\r()[];"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


# ============================================================
# S-expression parser
# ============================================================

def _parse_sexp(tokens, pos):
    """Parse one S-expression starting at pos. Return (sexp, new_pos)."""
    if pos >= len(tokens):
        raise ValueError("Unexpected end of input")
    tok = tokens[pos]
    if tok in ("(", "["):
        close = ")" if tok == "(" else "]"
        result = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != close:
            child, pos = _parse_sexp(tokens, pos)
            result.append(child)
        if pos >= len(tokens):
            raise ValueError(f"Missing closing '{close}'")
        pos += 1  # skip closing bracket
        return result, pos
    else:
        return tok, pos + 1


def _parse_all_sexps(text):
    """Parse all top-level S-expressions from text."""
    tokens = _tokenize(text)
    results = []
    pos = 0
    while pos < len(tokens):
        if tokens[pos] == "(":
            sexp, pos = _parse_sexp(tokens, pos)
            results.append(sexp)
        else:
            pos += 1
    return results


# ============================================================
# FPCore expression builder
# ============================================================

def _build_expr(sexp):
    """Convert a parsed S-expression into an AST node."""
    if isinstance(sexp, str):
        # Try number
        try:
            return Num(float(sexp))
        except ValueError:
            pass
        # Constants
        if sexp == "PI":
            return Num(math.pi)
        if sexp == "E":
            return Num(math.e)
        if sexp == "INFINITY":
            return Num(float("inf"))
        # Variable
        return Var(sexp)

    if not isinstance(sexp, list) or len(sexp) == 0:
        raise ValueError(f"Cannot parse expression: {sexp}")

    head = sexp[0]

    # Conditional
    if head == "if":
        return If(_build_expr(sexp[1]), _build_expr(sexp[2]), _build_expr(sexp[3]))

    # Let / let*
    if head in ("let", "let*"):
        bindings = []
        for binding in sexp[1]:
            bname = binding[0]
            bexpr = _build_expr(binding[1])
            bindings.append((bname, bexpr))
        body = _build_expr(sexp[2])
        return Let(bindings, body)

    # Annotation (! :prop val ... expr) — skip to last element
    if head == "!":
        return _build_expr(sexp[-1])

    # Operator application
    args = [_build_expr(a) for a in sexp[1:]]
    return Op(head, args)


# ============================================================
# Public API: parse_fpcore
# ============================================================

def parse_fpcore(text):
    """Parse FPCore text and return a list of FPCoreExpr objects.

    Each object has .name, .params, .body, and optional .pre attributes.
    """
    sexps = _parse_all_sexps(text)
    results = []
    for sexp in sexps:
        if not isinstance(sexp, list) or len(sexp) < 3 or sexp[0] != "FPCore":
            continue

        params = list(sexp[1])
        name = None
        pre = None

        # Scan properties (pairs of :keyword value) before the final body expr
        i = 2
        while i < len(sexp) - 1:
            item = sexp[i]
            if isinstance(item, str) and item.startswith(":"):
                if item == ":name":
                    raw = sexp[i + 1]
                    name = raw.strip('"') if isinstance(raw, str) else str(raw)
                    i += 2
                elif item == ":pre":
                    pre = sexp[i + 1]
                    i += 2
                else:
                    # Skip unknown property + value
                    i += 2
            else:
                break

        body = _build_expr(sexp[-1])
        results.append(FPCoreExpr(name=name, params=params, body=body, pre=pre))

    return results


# ============================================================
# Float64 evaluator
# ============================================================

_F64_UNARY = {
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "fabs": math.fabs,
    "abs": math.fabs,
    "expm1": math.expm1,
    "log1p": math.log1p,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asinh": math.asinh,
    "acosh": math.acosh,
    "atanh": math.atanh,
    "cbrt": lambda x: math.copysign(abs(x) ** (1.0 / 3.0), x),
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
}

_F64_BINARY = {
    "+": lambda a, b: a + b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "pow": lambda a, b: a ** b,
    "hypot": math.hypot,
    "copysign": math.copysign,
    "atan2": math.atan2,
    "fmod": math.fmod,
    "fmin": min,
    "fmax": max,
}


def _eval_f64(node, env):
    """Recursively evaluate an AST node in float64."""
    if isinstance(node, Num):
        return float(node.value)
    if isinstance(node, Var):
        return float(env[node.name])
    if isinstance(node, Let):
        new_env = dict(env)
        for bname, bexpr in node.bindings:
            new_env[bname] = _eval_f64(bexpr, new_env)
        return _eval_f64(node.body, new_env)
    if isinstance(node, If):
        cond = _eval_f64(node.cond, env)
        return _eval_f64(node.then_expr, env) if cond else _eval_f64(node.else_expr, env)
    if isinstance(node, Op):
        op = node.op
        args = [_eval_f64(a, env) for a in node.args]
        # Unary minus
        if op == "-" and len(args) == 1:
            return -args[0]
        # Binary minus
        if op == "-" and len(args) == 2:
            return args[0] - args[1]
        # Unary ops
        if len(args) == 1 and op in _F64_UNARY:
            return _F64_UNARY[op](args[0])
        # Binary ops
        if len(args) == 2 and op in _F64_BINARY:
            return _F64_BINARY[op](args[0], args[1])
        # Comparisons / logic
        if op == ">":
            return float(args[0] > args[1])
        if op == "<":
            return float(args[0] < args[1])
        if op == ">=":
            return float(args[0] >= args[1])
        if op == "<=":
            return float(args[0] <= args[1])
        if op == "==":
            return float(args[0] == args[1])
        if op == "!=":
            return float(args[0] != args[1])
        if op == "and":
            return float(all(args))
        if op == "or":
            return float(any(args))
        if op == "not":
            return float(not args[0])
        raise ValueError(f"Unknown operator '{op}' with {len(args)} args")
    raise ValueError(f"Cannot evaluate node: {type(node)}")


def eval_float64(expr, bindings):
    """Evaluate a parsed FPCore expression in IEEE 754 float64.

    Parameters
    ----------
    expr : FPCoreExpr
        A parsed expression (from parse_fpcore).
    bindings : dict
        Maps parameter names to float values.

    Returns
    -------
    float
    """
    body = expr.body if isinstance(expr, FPCoreExpr) else expr
    return _eval_f64(body, bindings)


# ============================================================
# Arbitrary-precision evaluator (mpmath)
# ============================================================

def _eval_mp(node, env):
    """Recursively evaluate an AST node in mpmath arbitrary precision."""
    if isinstance(node, Num):
        return mpf(str(node.value))
    if isinstance(node, Var):
        v = env[node.name]
        return v if isinstance(v, mpf) else mpf(str(v))
    if isinstance(node, Let):
        new_env = dict(env)
        for bname, bexpr in node.bindings:
            new_env[bname] = _eval_mp(bexpr, new_env)
        return _eval_mp(node.body, new_env)
    if isinstance(node, If):
        cond = _eval_mp(node.cond, env)
        return _eval_mp(node.then_expr, env) if cond else _eval_mp(node.else_expr, env)
    if isinstance(node, Op):
        op = node.op
        args = [_eval_mp(a, env) for a in node.args]
        if op == "-" and len(args) == 1:
            return -args[0]
        if op == "-" and len(args) == 2:
            return args[0] - args[1]
        if op == "+":
            return args[0] + args[1]
        if op == "*":
            return args[0] * args[1]
        if op == "/":
            return args[0] / args[1]
        if op == "sqrt":
            return mp.sqrt(args[0])
        if op == "exp":
            return mp.exp(args[0])
        if op == "log":
            return mp.log(args[0])
        if op == "sin":
            return mp.sin(args[0])
        if op == "cos":
            return mp.cos(args[0])
        if op == "tan":
            return mp.tan(args[0])
        if op == "asin":
            return mp.asin(args[0])
        if op == "acos":
            return mp.acos(args[0])
        if op == "atan":
            return mp.atan(args[0])
        if op == "pow":
            return mp.power(args[0], args[1])
        if op == "fabs":
            return abs(args[0])
        if op == "cbrt":
            return mp.cbrt(args[0])
        if op == "expm1":
            return mp.expm1(args[0])
        if op == "log1p":
            return mp.log(1 + args[0])
        if op == "hypot":
            return mp.hypot(args[0], args[1])
        if op == "copysign":
            return abs(args[0]) * (1 if args[1] >= 0 else -1)
        if op == "sinh":
            return mp.sinh(args[0])
        if op == "cosh":
            return mp.cosh(args[0])
        if op == "tanh":
            return mp.tanh(args[0])
        # Comparisons
        if op == ">":
            return mpf(1) if args[0] > args[1] else mpf(0)
        if op == "<":
            return mpf(1) if args[0] < args[1] else mpf(0)
        if op == ">=":
            return mpf(1) if args[0] >= args[1] else mpf(0)
        if op == "<=":
            return mpf(1) if args[0] <= args[1] else mpf(0)
        if op == "==":
            return mpf(1) if args[0] == args[1] else mpf(0)
        if op == "and":
            return mpf(1) if all(a != 0 for a in args) else mpf(0)
        if op == "or":
            return mpf(1) if any(a != 0 for a in args) else mpf(0)
        raise ValueError(f"Unknown operator '{op}' with {len(args)} args (mpmath)")
    raise ValueError(f"Cannot evaluate node: {type(node)}")


def eval_exact(expr, bindings, prec=200):
    """Evaluate a parsed FPCore expression in arbitrary precision.

    Parameters
    ----------
    expr : FPCoreExpr
        A parsed expression (from parse_fpcore).
    bindings : dict
        Maps parameter names to numeric values.
    prec : int
        mpmath precision in bits (default 200).

    Returns
    -------
    mpf
    """
    mp.prec = prec
    body = expr.body if isinstance(expr, FPCoreExpr) else expr
    mp_bindings = {k: mpf(str(v)) for k, v in bindings.items()}
    return _eval_mp(body, mp_bindings)


# ============================================================
# Improved (rewritten) implementations
# ============================================================

def _improved_nmse_31(x):
    """sqrt(x+1) - sqrt(x) rewritten via conjugate multiplication.

    Multiply and divide by (sqrt(x+1) + sqrt(x)):
        (sqrt(x+1) - sqrt(x)) * (sqrt(x+1) + sqrt(x)) / (sqrt(x+1) + sqrt(x))
        = ((x+1) - x) / (sqrt(x+1) + sqrt(x))
        = 1 / (sqrt(x+1) + sqrt(x))
    """
    return 1.0 / (math.sqrt(x + 1.0) + math.sqrt(x))


def _improved_expm1(x):
    """exp(x) - 1 rewritten using the compensated expm1 library function.

    Near x=0, exp(x) rounds to 1.0 in float64, so exp(x)-1 = 0.
    math.expm1 computes exp(x)-1 directly without the subtraction.
    """
    return math.expm1(x)


def _improved_qlog(x):
    """log(1-x)/log(1+x) rewritten using log1p.

    Near x=0, log(1±x) suffers from 1±x rounding to 1.0.
    math.log1p computes log(1+y) directly.
    """
    return math.log1p(-x) / math.log1p(x)


def _improved_cos2(x):
    """(1-cos(x))/(x*x) rewritten using the half-angle identity.

    1 - cos(x) = 2*sin(x/2)^2, avoiding the subtraction from 1.
    For very small x, use the Taylor series: 1/2 - x^2/24 + x^4/720 - x^6/40320.
    """
    if abs(x) < 1e-4:
        # Taylor series for (1 - cos(x)) / x^2
        x2 = x * x
        return 0.5 - x2 / 24.0 + x2 * x2 / 720.0 - x2 * x2 * x2 / 40320.0
    half = x / 2.0
    s = math.sin(half)
    return 2.0 * s * s / (x * x)


def _improved_quadp(a, b, c):
    """Quadratic formula positive root, rationalized for stability.

    Standard: (-b + sqrt(b^2 - 4ac)) / (2a)
    When b >= 0, -b and +sqrt(...) nearly cancel. Rationalize:
        (-b + d)(-b - d) / ((2a)(-b - d)) = (b^2 - d^2) / (2a(-b-d))
        = 4ac / (2a(-b-d)) = 2c / (-b - d)
    When b < 0, the standard formula has no cancellation.
    """
    disc = b * b - 4.0 * a * c
    d = math.sqrt(disc)
    if b >= 0:
        return (2.0 * c) / (-b - d)
    else:
        return (-b + d) / (2.0 * a)


def _improved_sqrtexp(x):
    """sqrt((exp(2x)-1)/(exp(x)-1)) simplified algebraically.

    (exp(2x) - 1) / (exp(x) - 1) = (exp(x) + 1)(exp(x) - 1) / (exp(x) - 1)
                                   = exp(x) + 1

    So the expression simplifies to sqrt(exp(x) + 1), which has no
    cancellation issues. For very small x, exp(x) + 1 ≈ 2 + x, which
    is perfectly stable.
    """
    return math.sqrt(math.exp(x) + 1.0)


_IMPROVED_REGISTRY = {
    "NMSE example 3.1": _improved_nmse_31,
    "expm1 (example 3.7)": _improved_expm1,
    "qlog (example 3.10)": _improved_qlog,
    "cos2 (problem 3.4.1)": _improved_cos2,
    "quadp (p42, positive)": _improved_quadp,
    "sqrtexp (problem 3.4.4)": _improved_sqrtexp,
}


def get_improved(name):
    """Return an improved float64 function for the named expression.

    Parameters
    ----------
    name : str
        The :name property from the FPCore expression.

    Returns
    -------
    callable
        A function taking positional arguments matching the expression's
        parameter list, returning a float64 result with improved accuracy.
    """
    if name not in _IMPROVED_REGISTRY:
        raise KeyError(f"No improved version available for: {name}")
    return _IMPROVED_REGISTRY[name]
