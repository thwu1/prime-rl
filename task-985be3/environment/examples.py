"""Example function definitions for region decomposition."""


from lang import (Const, Var, BinOp, IfExpr, Call, Compare, And, Or, Not,
                  BoolConst, FuncDef, Region)

# Example 1: Simple 4-region function (inspired by Imandra region decomposition docs)
# f(x) = if x > 99 then 100
#         elif x > 20 then x + 9
#         elif x > -2 then 103
#         else 99
simple_func = FuncDef(
    name='f',
    params=['x'],
    body=IfExpr(
        cond=Compare('>', Var('x'), Const(99)),
        then_expr=Const(100),
        else_expr=IfExpr(
            cond=Compare('>', Var('x'), Const(20)),
            then_expr=BinOp('+', Var('x'), Const(9)),
            else_expr=IfExpr(
                cond=Compare('>', Var('x'), Const(-2)),
                then_expr=Const(103),
                else_expr=Const(99)
            )
        )
    )
)

# Example 2: Function with a dead (infeasible) branch
# h(x) = if x > 10 then (if x < 5 then 999 else x * 2) else x + 1
# The branch x > 10 AND x < 5 is infeasible and should be eliminated.
dead_branch_func = FuncDef(
    name='h',
    params=['x'],
    body=IfExpr(
        cond=Compare('>', Var('x'), Const(10)),
        then_expr=IfExpr(
            cond=Compare('<', Var('x'), Const(5)),
            then_expr=Const(999),
            else_expr=BinOp('*', Var('x'), Const(2))
        ),
        else_expr=BinOp('+', Var('x'), Const(1))
    )
)

# Example 3: Multi-argument function
# g(x, y) = if x > y then x - y elif x == y then 0 else y - x
multi_arg_func = FuncDef(
    name='g',
    params=['x', 'y'],
    body=IfExpr(
        cond=Compare('>', Var('x'), Var('y')),
        then_expr=BinOp('-', Var('x'), Var('y')),
        else_expr=IfExpr(
            cond=Compare('==', Var('x'), Var('y')),
            then_expr=Const(0),
            else_expr=BinOp('-', Var('y'), Var('x'))
        )
    )
)

# Example 4: Quadrant/axis classifier (9 regions)
# classify(x, y):
#   x > 0: y > 0 -> 1, y == 0 -> 2, y < 0 -> 3
#   x == 0: y > 0 -> 4, y == 0 -> 5, y < 0 -> 6
#   x < 0: y > 0 -> 7, y == 0 -> 8, y < 0 -> 9
def _if3(var, pos_val, zero_val, neg_val):
    return IfExpr(
        Compare('>', var, Const(0)), pos_val,
        IfExpr(Compare('==', var, Const(0)), zero_val, neg_val))

nested_func = FuncDef(
    name='classify',
    params=['x', 'y'],
    body=IfExpr(
        cond=Compare('>', Var('x'), Const(0)),
        then_expr=_if3(Var('y'), Const(1), Const(2), Const(3)),
        else_expr=IfExpr(
            cond=Compare('==', Var('x'), Const(0)),
            then_expr=_if3(Var('y'), Const(4), Const(5), Const(6)),
            else_expr=_if3(Var('y'), Const(7), Const(8), Const(9))
        )
    )
)

# Example 5: Recursive function
# sum_to(n) = if n <= 0 then 0 else n + sum_to(n - 1)
recursive_func = FuncDef(
    name='sum_to',
    params=['n'],
    body=IfExpr(
        cond=Compare('<=', Var('n'), Const(0)),
        then_expr=Const(0),
        else_expr=BinOp('+', Var('n'),
                        Call('sum_to', [BinOp('-', Var('n'), Const(1))]))
    ),
    is_recursive=True
)

# Example 6: Clamp function (3 regions)
# clamp(x) = if x < 0 then 0 elif x > 100 then 100 else x
clamp_func = FuncDef(
    name='clamp',
    params=['x'],
    body=IfExpr(
        cond=Compare('<', Var('x'), Const(0)),
        then_expr=Const(0),
        else_expr=IfExpr(
            cond=Compare('>', Var('x'), Const(100)),
            then_expr=Const(100),
            else_expr=Var('x')
        )
    )
)
