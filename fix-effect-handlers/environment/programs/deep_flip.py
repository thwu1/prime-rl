"""Deep multi-shot handler: enumerate boolean combinations."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=Let("a", Do("Flip"),
                 Let("b", Do("Flip"),
                     Seq(Print(Var("a")), Print(Var("b"))))),
        handlers=[HandlerClause("Flip", [], "resume",
                                Seq(App(Var("resume"), [BoolLit(True)]),
                                    App(Var("resume"), [BoolLit(False)])))],
    )
    return prog, UNIT, [
        "True", "True", "True", "False",
        "False", "True", "False", "False",
    ]
