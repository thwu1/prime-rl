"""Multi-shot with single effect site (no deep handler needed)."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=If(Do("Flip"), IntLit(10), IntLit(20)),
        handlers=[HandlerClause("Flip", [], "resume",
                                BinOp("+",
                                      App(Var("resume"), [BoolLit(True)]),
                                      App(Var("resume"), [BoolLit(False)])))],
    )
    return prog, 30, []
