
"""
AST definitions for a small language with algebraic effect handlers.
Inspired by the Effekt research language's capability-passing approach.
"""

from dataclasses import dataclass, field
from typing import List, Optional


class Expr:
    pass


@dataclass
class IntLit(Expr):
    value: int

@dataclass
class BoolLit(Expr):
    value: bool

@dataclass
class StringLit(Expr):
    value: str

@dataclass
class Var(Expr):
    name: str

@dataclass
class BinOp(Expr):
    op: str
    left: Expr
    right: Expr

@dataclass
class UnaryOp(Expr):
    op: str
    operand: Expr

@dataclass
class IfExpr(Expr):
    cond: Expr
    then_branch: Expr
    else_branch: Expr

@dataclass
class Lambda(Expr):
    params: List[str]
    body: Expr

@dataclass
class App(Expr):
    func: Expr
    args: List[Expr]

@dataclass
class Let(Expr):
    name: str
    value: Expr
    body: Expr

@dataclass
class DefBinding(Expr):
    name: str
    params: List[str]
    value: Expr
    body: Expr

@dataclass
class Seq(Expr):
    exprs: List[Expr]

@dataclass
class Print(Expr):
    value: Expr

@dataclass
class Unit(Expr):
    pass


# --- Effect system AST ---

@dataclass
class EffectDecl:
    name: str
    operations: List['OpDecl']

@dataclass
class OpDecl:
    name: str
    params: List[str]

@dataclass
class DoExpr(Expr):
    """Perform an effect operation: do Op(args)"""
    op_name: str
    args: List[Expr]

@dataclass
class HandlerClause:
    op_name: str
    params: List[str]
    resume_name: str
    body: Expr

@dataclass
class ReturnClause:
    param: str
    body: Expr

@dataclass
class HandleExpr(Expr):
    """
    handle { body } with EffectName {
        return(x) => ret_expr
        Op(a, b, resume) => handler_body
    }
    """
    body: Expr
    effect_name: str
    return_clause: Optional[ReturnClause]
    op_clauses: List[HandlerClause]

@dataclass
class Program:
    effects: List[EffectDecl]
    main: Expr
