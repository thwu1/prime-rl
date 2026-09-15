"""Recursive effectful computation using LetRec."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=LetRec(
            "sum_to",
            Lam(["n"],
                If(BinOp("==", Var("n"), IntLit(0)),
                   IntLit(0),
                   Seq(Do("Emit", [Var("n")]),
                       BinOp("+", Var("n"),
                             App(Var("sum_to"),
                                 [BinOp("-", Var("n"), IntLit(1))]))))),
            App(Var("sum_to"), [IntLit(4)])),
        handlers=[HandlerClause("Emit", ["x"], "resume",
                                App(Var("resume"), [UnitLit()]))],
    )
    return prog, 10, []
