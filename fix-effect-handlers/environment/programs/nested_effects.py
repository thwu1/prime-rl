"""Nested handlers with different effects: Ask propagates through Greet."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=Handle(
            body=Let("name", Do("Ask"),
                     Do("Greet", [Var("name")])),
            handlers=[HandlerClause("Greet", ["name"], "resume",
                                    Seq(Print(Var("name")),
                                        App(Var("resume"), [UnitLit()])))],
        ),
        handlers=[HandlerClause("Ask", [], "resume",
                                App(Var("resume"), [StrLit("World")]))],
    )
    return prog, UNIT, ["World"]
