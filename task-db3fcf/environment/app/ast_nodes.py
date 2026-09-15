"""AST node definitions for the MiniCalc language."""


class Program:
    def __init__(self, functions, main_body):
        self.functions = functions  # list of FuncDef
        self.main_body = main_body  # list of Stmt


class FuncDef:
    def __init__(self, name, params, body):
        self.name = name      # str
        self.params = params   # list of str
        self.body = body       # list of Stmt


# Statements

class AssignStmt:
    def __init__(self, name, expr):
        self.name = name  # str
        self.expr = expr  # Expr


class IfStmt:
    def __init__(self, cond, then_body, else_body=None):
        self.cond = cond            # Expr
        self.then_body = then_body  # list of Stmt
        self.else_body = else_body  # list of Stmt or None


class WhileStmt:
    def __init__(self, cond, body):
        self.cond = cond  # Expr
        self.body = body  # list of Stmt


class ReturnStmt:
    def __init__(self, expr):
        self.expr = expr  # Expr


class PrintStmt:
    def __init__(self, exprs):
        self.exprs = exprs  # list of Expr


# Expressions

class IntLit:
    def __init__(self, value):
        self.value = value  # int


class VarRef:
    def __init__(self, name):
        self.name = name  # str


class BinOp:
    def __init__(self, op, left, right):
        self.op = op      # str: '+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=', '&&', '||'
        self.left = left   # Expr
        self.right = right  # Expr


class UnaryOp:
    def __init__(self, op, operand):
        self.op = op          # str: '-', '!'
        self.operand = operand  # Expr


class FuncCall:
    def __init__(self, name, args):
        self.name = name  # str
        self.args = args  # list of Expr
