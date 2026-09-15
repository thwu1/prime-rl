"""Common subexpression elimination pass.

Within a basic block, when a Call to a pure operator computes the same
expression (same operator and same argument variables) as a previous Call
whose result is still valid (all argument variables have single static
definitions), the second Call is replaced with a Copy from the first
result.  Commutative operators (+ * == !=) also match the reversed
argument order.

The available-expression set is conservatively reset at every Label
instruction, since an unknown predecessor might jump to that label
without the expression having been computed.
"""
from collections import defaultdict
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)

PURE_OPS = frozenset({
    '+', '-', '*', '/', '%',
    '==', '!=', '<', '<=', '>', '>=',
    'unary_-', 'not',
})

COMMUTATIVE_OPS = frozenset({'+', '*', '==', '!='})


def _def_counts(instructions):
    counts = defaultdict(int)
    for insn in instructions:
        if isinstance(insn, (LoadIntConst, LoadBoolConst, Copy, Call)):
            counts[insn.dest.name] += 1
    return counts


def run(instructions):
    defs = _def_counts(instructions)
    available = {}

    result = []
    for insn in instructions:
        # Reset at control-flow join points
        if isinstance(insn, Label):
            available = {}
            result.append(insn)
            continue

        if (isinstance(insn, Call)
                and insn.fun.name in PURE_OPS
                and defs[insn.dest.name] == 1):

            args_stable = all(defs[a.name] == 1 for a in insn.args)
            key = (insn.fun.name, tuple(a.name for a in insn.args))

            if args_stable and key in available:
                prev_dest = available[key]
                if defs[prev_dest] == 1:
                    result.append(Copy(IRVar(prev_dest), insn.dest))
                    continue

            if (args_stable
                    and insn.fun.name in COMMUTATIVE_OPS
                    and len(insn.args) == 2):
                ck = (insn.fun.name,
                      (insn.args[1].name, insn.args[0].name))
                if ck in available:
                    prev_dest = available[ck]
                    if defs[prev_dest] == 1:
                        result.append(Copy(IRVar(prev_dest), insn.dest))
                        continue

            if args_stable:
                available[key] = insn.dest.name
                if (insn.fun.name in COMMUTATIVE_OPS
                        and len(insn.args) == 2):
                    ck = (insn.fun.name,
                          (insn.args[1].name, insn.args[0].name))
                    available[ck] = insn.dest.name

        result.append(insn)
    return result
