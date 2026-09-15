# Expression nodes

class Literal:
    def __init__(self, value):
        self.value = value


class Grouping:
    def __init__(self, expression):
        self.expression = expression


class Unary:
    def __init__(self, operator, right):
        self.operator = operator
        self.right = right


class Binary:
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right


class Variable:
    def __init__(self, name):
        self.name = name


class Assign:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class Logical:
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right


class Call:
    def __init__(self, callee, paren, arguments):
        self.callee = callee
        self.paren = paren
        self.arguments = arguments


class Get:
    def __init__(self, obj, name):
        self.obj = obj
        self.name = name


class Set:
    def __init__(self, obj, name, value):
        self.obj = obj
        self.name = name
        self.value = value


class This:
    def __init__(self, keyword):
        self.keyword = keyword


class Super:
    def __init__(self, keyword, method):
        self.keyword = keyword
        self.method = method


# Statement nodes

class ExpressionStmt:
    def __init__(self, expression):
        self.expression = expression


class PrintStmt:
    def __init__(self, expression):
        self.expression = expression


class VarStmt:
    def __init__(self, name, initializer):
        self.name = name
        self.initializer = initializer


class BlockStmt:
    def __init__(self, statements):
        self.statements = statements


class IfStmt:
    def __init__(self, condition, then_branch, else_branch):
        self.condition = condition
        self.then_branch = then_branch
        self.else_branch = else_branch


class WhileStmt:
    def __init__(self, condition, body):
        self.condition = condition
        self.body = body


class FunctionStmt:
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body


class ReturnStmt:
    def __init__(self, keyword, value):
        self.keyword = keyword
        self.value = value


class ClassStmt:
    def __init__(self, name, superclass, methods):
        self.name = name
        self.superclass = superclass
        self.methods = methods
