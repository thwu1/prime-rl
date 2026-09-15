
"""
Complete AST builder: transforms lark parse trees into AST nodes.
Handles all language constructs including algebraic effects.
"""

from lark import Transformer, Token
from ast_nodes import *


class ASTBuilder(Transformer):

    # --- Literals ---

    def integer(self, items):
        return IntLit(int(items[0]))

    def string_lit(self, items):
        s = str(items[0])
        return StringLit(s[1:-1])

    def true_lit(self, items):
        return BoolLit(True)

    def false_lit(self, items):
        return BoolLit(False)

    def unit_lit(self, items):
        return Unit()

    def variable(self, items):
        return Var(str(items[0]))

    # --- Binary operators ---

    def add(self, items):
        return BinOp('+', items[0], items[1])

    def sub(self, items):
        return BinOp('-', items[0], items[1])

    def mul(self, items):
        return BinOp('*', items[0], items[1])

    def div(self, items):
        return BinOp('/', items[0], items[1])

    def mod_op(self, items):
        return BinOp('%', items[0], items[1])

    def str_concat(self, items):
        return BinOp('++', items[0], items[1])

    def eq(self, items):
        return BinOp('==', items[0], items[1])

    def neq(self, items):
        return BinOp('!=', items[0], items[1])

    def lt(self, items):
        return BinOp('<', items[0], items[1])

    def gt(self, items):
        return BinOp('>', items[0], items[1])

    def leq(self, items):
        return BinOp('<=', items[0], items[1])

    def geq(self, items):
        return BinOp('>=', items[0], items[1])

    # --- Unary operators ---

    def negate(self, items):
        return UnaryOp('-', items[0])

    def logical_not(self, items):
        return UnaryOp('not', items[0])

    # --- Control flow ---

    def if_expr(self, items):
        return IfExpr(cond=items[0], then_branch=items[1], else_branch=items[2])

    # --- Functions ---

    def lambda_expr(self, items):
        if len(items) == 2:
            params, body = items
            return Lambda(params=list(params), body=body)
        else:
            return Lambda(params=[], body=items[0])

    def application(self, items):
        if len(items) == 2:
            func, args = items
            return App(func=func, args=list(args))
        else:
            return App(func=items[0], args=[])

    # --- Bindings ---

    def val_binding(self, items):
        return Let(name=str(items[0]), value=items[1], body=items[2])

    def def_binding(self, items):
        if len(items) == 4:
            name, params, value, body = items
            return DefBinding(name=str(name), params=list(params),
                              value=value, body=body)
        else:
            name, value, body = items
            return DefBinding(name=str(name), params=[],
                              value=value, body=body)

    # --- Sequences ---

    def sequence(self, items):
        if len(items) == 1:
            return items[0]
        return Seq(exprs=list(items))

    # --- Print ---

    def print_expr(self, items):
        return Print(value=items[0])

    # --- Effect declarations ---

    def effect_decl(self, items):
        name = str(items[0])
        ops = list(items[1:])
        return EffectDecl(name=name, operations=ops)

    def op_decl(self, items):
        name = str(items[0])
        if len(items) > 1:
            params = list(items[1])
        else:
            params = []
        return OpDecl(name=name, params=params)

    # --- Handle / Do ---

    def handle_expr(self, items):
        body = items[0]
        effect_name = str(items[1])
        return_clause = None
        op_clauses = []
        for item in items[2:]:
            if isinstance(item, ReturnClause):
                return_clause = item
            elif isinstance(item, HandlerClause):
                op_clauses.append(item)
        return HandleExpr(body=body, effect_name=effect_name,
                          return_clause=return_clause, op_clauses=op_clauses)

    def return_clause(self, items):
        param = str(items[0])
        body = items[1]
        return ReturnClause(param=param, body=body)

    def op_clause(self, items):
        op_name = str(items[0])
        if len(items) == 3:
            all_params = list(items[1])
            body = items[2]
        else:
            all_params = []
            body = items[1]
        # Last parameter is always the resume function name
        if all_params:
            resume_name = all_params[-1]
            op_params = all_params[:-1]
        else:
            resume_name = "resume"
            op_params = []
        return HandlerClause(op_name=op_name, params=op_params,
                             resume_name=resume_name, body=body)

    def do_expr(self, items):
        op_name = str(items[0])
        if len(items) > 1:
            args = list(items[1])
        else:
            args = []
        return DoExpr(op_name=op_name, args=args)

    # --- Lists ---

    def param_list(self, items):
        return [str(t) for t in items]

    def arg_list(self, items):
        return list(items)

    # --- Program ---

    def start(self, items):
        effects = list(items[:-1])
        main = items[-1]
        return Program(effects=effects, main=main)
