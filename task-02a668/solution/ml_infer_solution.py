"""Hindley-Milner type inference using Algorithm W.

Implements complete type inference for the language defined in ml_ast.
"""

from ml_ast import *
from ml_types import Type, TInt, TBool, TUnit, TVar, TArrow, TPair, TList, Scheme
from ml_unify import Substitution, UnificationError, unify


class InferenceError(Exception):
    """Raised when type inference fails."""
    pass


class TypeEnv:
    """Type environment: maps variable names to type schemes."""

    def __init__(self, bindings=None):
        self.bindings = bindings if bindings is not None else {}

    def extend(self, name, scheme):
        new = dict(self.bindings)
        new[name] = scheme
        return TypeEnv(new)

    def lookup(self, name):
        if name not in self.bindings:
            raise InferenceError(f"Unbound variable: {name}")
        return self.bindings[name]


# ---------------------------------------------------------------------------
# Fresh variable generation
# ---------------------------------------------------------------------------

_counter = 0


def _reset():
    global _counter
    _counter = 0


def fresh_var():
    global _counter
    _counter += 1
    return TVar(f"_t{_counter}")


# ---------------------------------------------------------------------------
# Free variable computation
# ---------------------------------------------------------------------------

def free_vars(t):
    """Free type variables in a type."""
    if isinstance(t, (TInt, TBool, TUnit)):
        return set()
    elif isinstance(t, TVar):
        return {t.name}
    elif isinstance(t, TArrow):
        return free_vars(t.arg) | free_vars(t.ret)
    elif isinstance(t, TPair):
        return free_vars(t.fst) | free_vars(t.snd)
    elif isinstance(t, TList):
        return free_vars(t.elem)
    else:
        return set()


def free_vars_scheme(scheme):
    """Free type variables in a type scheme (excluding quantified vars)."""
    return free_vars(scheme.body) - scheme.vars


def free_vars_env(env):
    """Free type variables in all schemes in an environment."""
    result = set()
    for scheme in env.bindings.values():
        result |= free_vars_scheme(scheme)
    return result


# ---------------------------------------------------------------------------
# Substitution on schemes and environments
# ---------------------------------------------------------------------------

def apply_subst_scheme(subst, scheme):
    """Apply substitution to a type scheme, preserving bound variables."""
    restricted = Substitution({
        k: v for k, v in subst.mapping.items()
        if k not in scheme.vars
    })
    return Scheme(scheme.vars, restricted.apply(scheme.body))


def apply_subst_env(subst, env):
    """Apply substitution to every scheme in an environment."""
    return TypeEnv({
        k: apply_subst_scheme(subst, v)
        for k, v in env.bindings.items()
    })


# ---------------------------------------------------------------------------
# Generalization and instantiation
# ---------------------------------------------------------------------------

def generalize(env, t):
    """Generalize type t over variables not free in env."""
    vars_to_quantify = free_vars(t) - free_vars_env(env)
    return Scheme(frozenset(vars_to_quantify), t)


def instantiate(scheme):
    """Replace quantified variables with fresh type variables."""
    subst_map = {}
    for var in scheme.vars:
        subst_map[var] = fresh_var()
    s = Substitution(subst_map)
    return s.apply(scheme.body)


# ---------------------------------------------------------------------------
# Operator typing
# ---------------------------------------------------------------------------

_ARITH_OPS = {"+", "-", "*", "/"}
_CMP_OPS = {"==", "<", ">", "<=", ">="}
_LOGIC_OPS = {"&&", "||"}


# ---------------------------------------------------------------------------
# Algorithm W
# ---------------------------------------------------------------------------

def infer(env, expr):
    """Infer the type of expr in environment env.

    Returns (substitution, type).
    """
    if isinstance(expr, IntLit):
        return Substitution(), TInt()

    elif isinstance(expr, BoolLit):
        return Substitution(), TBool()

    elif isinstance(expr, Unit):
        return Substitution(), TUnit()

    elif isinstance(expr, Var):
        scheme = env.lookup(expr.name)
        t = instantiate(scheme)
        return Substitution(), t

    elif isinstance(expr, BinOp):
        return _infer_binop(env, expr)

    elif isinstance(expr, Not):
        s1, t1 = infer(env, expr.expr)
        s2 = unify(t1, TBool())
        return s2.compose(s1), TBool()

    elif isinstance(expr, Neg):
        s1, t1 = infer(env, expr.expr)
        s2 = unify(t1, TInt())
        return s2.compose(s1), TInt()

    elif isinstance(expr, If):
        return _infer_if(env, expr)

    elif isinstance(expr, Lam):
        tv = fresh_var()
        new_env = env.extend(expr.param, Scheme(frozenset(), tv))
        s1, t_body = infer(new_env, expr.body)
        return s1, TArrow(s1.apply(tv), t_body)

    elif isinstance(expr, App):
        return _infer_app(env, expr)

    elif isinstance(expr, Let):
        return _infer_let(env, expr)

    elif isinstance(expr, LetRec):
        return _infer_letrec(env, expr)

    elif isinstance(expr, MkPair):
        s1, t1 = infer(env, expr.fst)
        s2, t2 = infer(apply_subst_env(s1, env), expr.snd)
        return s2.compose(s1), TPair(s2.apply(t1), t2)

    elif isinstance(expr, Fst):
        a, b = fresh_var(), fresh_var()
        s1, t1 = infer(env, expr.expr)
        s2 = unify(t1, TPair(a, b))
        return s2.compose(s1), s2.apply(a)

    elif isinstance(expr, Snd):
        a, b = fresh_var(), fresh_var()
        s1, t1 = infer(env, expr.expr)
        s2 = unify(t1, TPair(a, b))
        return s2.compose(s1), s2.apply(b)

    elif isinstance(expr, Nil):
        return Substitution(), TList(fresh_var())

    elif isinstance(expr, Cons):
        return _infer_cons(env, expr)

    elif isinstance(expr, MatchList):
        return _infer_match(env, expr)

    else:
        raise InferenceError(f"Unknown expression type: {type(expr)}")


def _infer_binop(env, expr):
    if expr.op in _ARITH_OPS:
        s1, t1 = infer(env, expr.left)
        s2 = unify(t1, TInt())
        s_acc = s2.compose(s1)
        s3, t2 = infer(apply_subst_env(s_acc, env), expr.right)
        s4 = unify(t2, TInt())
        return s4.compose(s3).compose(s_acc), TInt()
    elif expr.op in _CMP_OPS:
        s1, t1 = infer(env, expr.left)
        s2 = unify(t1, TInt())
        s_acc = s2.compose(s1)
        s3, t2 = infer(apply_subst_env(s_acc, env), expr.right)
        s4 = unify(t2, TInt())
        return s4.compose(s3).compose(s_acc), TBool()
    elif expr.op in _LOGIC_OPS:
        s1, t1 = infer(env, expr.left)
        s2 = unify(t1, TBool())
        s_acc = s2.compose(s1)
        s3, t2 = infer(apply_subst_env(s_acc, env), expr.right)
        s4 = unify(t2, TBool())
        return s4.compose(s3).compose(s_acc), TBool()
    else:
        raise InferenceError(f"Unknown operator: {expr.op}")


def _infer_if(env, expr):
    s1, t_cond = infer(env, expr.cond)
    s2 = unify(t_cond, TBool())
    s_acc = s2.compose(s1)

    s3, t_then = infer(apply_subst_env(s_acc, env), expr.then_)
    s_acc = s3.compose(s_acc)

    s4, t_else = infer(apply_subst_env(s_acc, env), expr.else_)
    s5 = unify(s4.apply(t_then), t_else)

    return s5.compose(s4).compose(s_acc), s5.apply(t_else)


def _infer_app(env, expr):
    tv = fresh_var()
    s1, t_func = infer(env, expr.func)
    s2, t_arg = infer(apply_subst_env(s1, env), expr.arg)
    s3 = unify(s2.apply(t_func), TArrow(t_arg, tv))
    return s3.compose(s2).compose(s1), s3.apply(tv)


def _infer_let(env, expr):
    s1, t1 = infer(env, expr.rhs)
    env1 = apply_subst_env(s1, env)
    scheme = generalize(env1, t1)
    new_env = env1.extend(expr.name, scheme)
    s2, t2 = infer(new_env, expr.body)
    return s2.compose(s1), t2


def _infer_letrec(env, expr):
    tv = fresh_var()
    rec_env = env.extend(expr.name, Scheme(frozenset(), tv))
    s1, t1 = infer(rec_env, expr.rhs)
    s2 = unify(s1.apply(tv), t1)
    s_acc = s2.compose(s1)

    env1 = apply_subst_env(s_acc, env)
    scheme = generalize(env1, s_acc.apply(tv))
    new_env = env1.extend(expr.name, scheme)
    s3, t2 = infer(new_env, expr.body)
    return s3.compose(s_acc), t2


def _infer_cons(env, expr):
    s1, t_head = infer(env, expr.head)
    s2, t_tail = infer(apply_subst_env(s1, env), expr.tail)
    s3 = unify(t_tail, TList(s2.apply(t_head)))
    return s3.compose(s2).compose(s1), s3.apply(t_tail)


def _infer_match(env, expr):
    # Infer scrutinee type and unify with list type
    s1, t_scr = infer(env, expr.expr)
    a = fresh_var()
    s2 = unify(t_scr, TList(a))
    s_acc = s2.compose(s1)

    # Infer nil case
    env_nil = apply_subst_env(s_acc, env)
    s3, t_nil = infer(env_nil, expr.nil_case)
    s_acc = s3.compose(s_acc)

    # Infer cons case with head and tail bindings
    elem_t = s_acc.apply(a)
    list_t = TList(elem_t)
    env_cons = apply_subst_env(s_acc, env)
    env_cons = env_cons.extend(expr.head_var, Scheme(frozenset(), elem_t))
    env_cons = env_cons.extend(expr.tail_var, Scheme(frozenset(), list_t))
    s4, t_cons = infer(env_cons, expr.cons_case)

    # Unify nil and cons result types
    s5 = unify(s4.apply(t_nil), t_cons)
    s_total = s5.compose(s4).compose(s_acc)
    return s_total, s5.apply(t_cons)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def infer_program(expr):
    """Infer the type of a top-level expression.

    Returns the fully resolved (substitution-applied) type.
    Raises InferenceError on type errors.
    """
    _reset()
    env = TypeEnv()
    try:
        s, t = infer(env, expr)
        return s.apply(t)
    except UnificationError as e:
        raise InferenceError(str(e))
