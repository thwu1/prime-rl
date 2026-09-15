"""Handler with resume and return clause interaction."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=Do("Get"),
        handlers=[HandlerClause("Get", [], "resume",
                                App(Var("resume"), [IntLit(21)]))],
        return_clause=ReturnClause("x",
                                   BinOp("+",
                                         BinOp("*", Var("x"), IntLit(2)),
                                         IntLit(1))),
    )
    return prog, 43, []
