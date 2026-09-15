"""AST node definitions for Mini-ML.

The language supports:
- Integer and boolean literals, unit values
- Arithmetic operators (+, -, *, /)
- Comparison operators (==, <, >, <=, >=)
- Logical operators (&&, ||)
- Unary negation (arithmetic and logical)
- If-then-else expressions
- Lambda abstractions and function application
- Let bindings and recursive let bindings
- Pairs with fst/snd projections
- Lists with nil, cons, and pattern matching
"""
from dataclasses import dataclass


class Expr:
    """Base class for all expressions."""
    pass


@dataclass
class IntLit(Expr):
    """Integer literal."""
    value: int


@dataclass
class BoolLit(Expr):
    """Boolean literal."""
    value: bool


@dataclass
class Unit(Expr):
    """Unit value ()."""
    pass


@dataclass
class Var(Expr):
    """Variable reference."""
    name: str


@dataclass
class BinOp(Expr):
    """Binary operation.

    Supported ops: '+', '-', '*', '/', '==', '<', '>', '<=', '>=', '&&', '||'
    """
    op: str
    left: Expr
    right: Expr


@dataclass
class Not(Expr):
    """Logical negation."""
    expr: Expr


@dataclass
class Neg(Expr):
    """Arithmetic negation."""
    expr: Expr


@dataclass
class If(Expr):
    """If-then-else expression."""
    cond: Expr
    then_: Expr
    else_: Expr


@dataclass
class Lam(Expr):
    """Lambda abstraction: fun param -> body."""
    param: str
    body: Expr


@dataclass
class App(Expr):
    """Function application."""
    func: Expr
    arg: Expr


@dataclass
class Let(Expr):
    """Let binding: let name = rhs in body."""
    name: str
    rhs: Expr
    body: Expr


@dataclass
class LetRec(Expr):
    """Recursive let binding: let rec name = rhs in body.

    The bound name is available in rhs for recursive calls.
    """
    name: str
    rhs: Expr
    body: Expr


@dataclass
class MkPair(Expr):
    """Pair constructor: (fst, snd)."""
    fst: Expr
    snd: Expr


@dataclass
class Fst(Expr):
    """First projection of a pair."""
    expr: Expr


@dataclass
class Snd(Expr):
    """Second projection of a pair."""
    expr: Expr


@dataclass
class Nil(Expr):
    """Empty list []."""
    pass


@dataclass
class Cons(Expr):
    """List cons: head :: tail."""
    head: Expr
    tail: Expr


@dataclass
class MatchList(Expr):
    """Pattern match on a list.

    match expr with
    | [] -> nil_case
    | head_var :: tail_var -> cons_case
    """
    expr: Expr
    nil_case: Expr
    head_var: str
    tail_var: str
    cons_case: Expr
