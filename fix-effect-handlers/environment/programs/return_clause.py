"""Basic return clause test."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=IntLit(21),
        handlers=[],
        return_clause=ReturnClause("x", BinOp("*", Var("x"), IntLit(2))),
    )
    return prog, 42, []
