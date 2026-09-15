"""Basic single-effect handler test."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=Do("Ask"),
        handlers=[HandlerClause("Ask", [], "resume",
                                App(Var("resume"), [IntLit(42)]))],
    )
    return prog, 42, []
