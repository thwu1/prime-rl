"""Abort (non-resumptive) handler test."""
import sys; sys.path.insert(0, "/app")
from effekt import *


def build():
    prog = Handle(
        body=BinOp("+", IntLit(1), Do("Fail", [StrLit("err")])),
        handlers=[HandlerClause("Fail", ["msg"], "resume", IntLit(-1))],
    )
    return prog, -1, []
