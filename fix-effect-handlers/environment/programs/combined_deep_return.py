"""Combined deep handler with return clause."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=Seq(Do("Emit", [IntLit(10)]), Do("Emit", [IntLit(20)]),
                 IntLit(0)),
        handlers=[HandlerClause("Emit", ["x"], "resume",
                                BinOp("+", Var("x"),
                                      App(Var("resume"), [UnitLit()])))],
        return_clause=ReturnClause("v", BinOp("+", Var("v"), IntLit(100))),
    )
    return prog, 130, []
