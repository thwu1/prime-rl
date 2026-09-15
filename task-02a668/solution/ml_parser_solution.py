"""Mini-ML parser using the Lark parsing library."""
import os
from lark import Lark, Transformer, v_args
from ml_ast import *

_GRAMMAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grammar.lark")
with open(_GRAMMAR_PATH) as _f:
    _grammar_text = _f.read()

_parser = Lark(_grammar_text, parser="earley", start="start")


@v_args(inline=True)
class MLTransformer(Transformer):
    def start(self, e):
        return e

    def int_lit(self, n):
        return IntLit(int(n))

    def true_lit(self):
        return BoolLit(True)

    def false_lit(self):
        return BoolLit(False)

    def unit_lit(self):
        return Unit()

    def nil_lit(self):
        return Nil()

    def var(self, name):
        return Var(str(name))

    def pair(self, a, b):
        return MkPair(a, b)

    def binop_add(self, a, b):
        return BinOp("+", a, b)

    def binop_sub(self, a, b):
        return BinOp("-", a, b)

    def binop_mul(self, a, b):
        return BinOp("*", a, b)

    def binop_div(self, a, b):
        return BinOp("/", a, b)

    def binop_eq(self, a, b):
        return BinOp("==", a, b)

    def binop_lt(self, a, b):
        return BinOp("<", a, b)

    def binop_gt(self, a, b):
        return BinOp(">", a, b)

    def binop_le(self, a, b):
        return BinOp("<=", a, b)

    def binop_ge(self, a, b):
        return BinOp(">=", a, b)

    def binop_or(self, a, b):
        return BinOp("||", a, b)

    def binop_and(self, a, b):
        return BinOp("&&", a, b)

    def not_expr(self, e):
        return Not(e)

    def neg_expr(self, e):
        return Neg(e)

    def if_expr(self, c, t, e):
        return If(c, t, e)

    def lam(self, name, body):
        return Lam(str(name), body)

    def application(self, f, a):
        return App(f, a)

    def let_bind(self, name, rhs, body):
        return Let(str(name), rhs, body)

    def letrec(self, name, rhs, body):
        return LetRec(str(name), rhs, body)

    def fst_expr(self, e):
        return Fst(e)

    def snd_expr(self, e):
        return Snd(e)

    def cons(self, h, t):
        return Cons(h, t)

    def match_list(self, scrut, nil_case, h, t, cons_case):
        return MatchList(scrut, nil_case, str(h), str(t), cons_case)


_transformer = MLTransformer()


def parse(source: str):
    """Parse Mini-ML source code into an AST."""
    tree = _parser.parse(source)
    return _transformer.transform(tree)
