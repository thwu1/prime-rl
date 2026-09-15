"""Deep handler: accumulate repeated effects."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=Seq(Do("Emit", [IntLit(1)]), Do("Emit", [IntLit(2)]),
                 Do("Emit", [IntLit(3)]), IntLit(0)),
        handlers=[HandlerClause("Emit", ["x"], "resume",
                                BinOp("+", Var("x"),
                                      App(Var("resume"), [UnitLit()])))],
    )
    return prog, 6, []
