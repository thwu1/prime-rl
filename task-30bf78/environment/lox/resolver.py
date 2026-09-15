import sys
from .ast_nodes import (
    Literal, Grouping, Unary, Binary, Variable, Assign, Logical, Call,
    Get, Set, This, Super, ExpressionStmt, PrintStmt, VarStmt, BlockStmt,
    IfStmt, WhileStmt, FunctionStmt, ReturnStmt, ClassStmt,
)
from .tokens import TokenType

FT_NONE = 0
FT_FUNCTION = 1
FT_METHOD = 2
FT_INITIALIZER = 3

CT_NONE = 0
CT_CLASS = 1
CT_SUBCLASS = 2


class Resolver:
    def __init__(self):
        self.scopes = []
        self.locals = {}
        self.current_function = FT_NONE
        self.current_class = CT_NONE
        self.had_error = False

    def resolve(self, node):
        if isinstance(node, list):
            for item in node:
                self.resolve(item)
            return

        if isinstance(node, BlockStmt):
            self.begin_scope()
            self.resolve(node.statements)
            self.end_scope()

        elif isinstance(node, VarStmt):
            self.declare(node.name)
            if node.initializer is not None:
                self.resolve(node.initializer)
            self.define(node.name)

        elif isinstance(node, Variable):
            if (
                self.scopes
                and self.scopes[-1].get(node.name.lexeme) is False
            ):
                self.error("Can't read local variable in its own initializer.")
            self.resolve_local(node, node.name)

        elif isinstance(node, Assign):
            self.resolve(node.value)
            self.resolve_local(node, node.name)

        elif isinstance(node, FunctionStmt):
            self.declare(node.name)
            self.define(node.name)
            self.resolve_function(node, FT_FUNCTION)

        elif isinstance(node, ExpressionStmt):
            self.resolve(node.expression)

        elif isinstance(node, IfStmt):
            self.resolve(node.condition)
            self.resolve(node.then_branch)
            if node.else_branch is not None:
                self.resolve(node.else_branch)

        elif isinstance(node, PrintStmt):
            self.resolve(node.expression)

        elif isinstance(node, ReturnStmt):
            if self.current_function == FT_NONE:
                self.error("Can't return from top-level code.")
            if node.value is not None:
                if self.current_function == FT_INITIALIZER:
                    self.error("Can't return a value from an initializer.")
                self.resolve(node.value)

        elif isinstance(node, WhileStmt):
            self.resolve(node.condition)
            self.resolve(node.body)

        elif isinstance(node, Binary):
            self.resolve(node.left)
            self.resolve(node.right)

        elif isinstance(node, Call):
            self.resolve(node.callee)
            for arg in node.arguments:
                self.resolve(arg)

        elif isinstance(node, Grouping):
            self.resolve(node.expression)

        elif isinstance(node, Logical):
            self.resolve(node.left)
            self.resolve(node.right)

        elif isinstance(node, Unary):
            self.resolve(node.right)

        elif isinstance(node, ClassStmt):
            enclosing_class = self.current_class
            self.current_class = CT_CLASS

            self.declare(node.name)
            self.define(node.name)

            if node.superclass is not None:
                if node.name.lexeme == node.superclass.name.lexeme:
                    self.error("A class can't inherit from itself.")
                self.current_class = CT_SUBCLASS
                self.resolve(node.superclass)
                self.begin_scope()
                self.scopes[-1]["super"] = True

            self.begin_scope()
            self.scopes[-1]["this"] = True

            for method in node.methods:
                declaration = FT_METHOD
                if method.name.lexeme == "init":
                    declaration = FT_INITIALIZER
                self.resolve_function(method, declaration)

            self.end_scope()
            if node.superclass is not None:
                self.end_scope()

            self.current_class = enclosing_class

        elif isinstance(node, Super):
            if self.current_class == CT_NONE:
                self.error("Can't use 'super' outside of a class.")
            elif self.current_class != CT_SUBCLASS:
                self.error("Can't use 'super' in a class with no superclass.")
            self.resolve_local(node, node.keyword)

        elif isinstance(node, Get):
            self.resolve(node.obj)

        elif isinstance(node, Set):
            self.resolve(node.value)
            self.resolve(node.obj)

        elif isinstance(node, This):
            if self.current_class == CT_NONE:
                self.error("Can't use 'this' outside of a class.")
            self.resolve_local(node, node.keyword)

        elif isinstance(node, Literal):
            pass

    def resolve_function(self, function, function_type):
        enclosing = self.current_function
        self.current_function = function_type
        self.begin_scope()
        for param in function.params:
            self.declare(param)
            self.define(param)
        self.resolve(function.body)
        self.end_scope()
        self.current_function = enclosing

    def resolve_local(self, expr, name):
        for i in range(len(self.scopes) - 1, -1, -1):
            if name.lexeme in self.scopes[i]:
                self.locals[id(expr)] = len(self.scopes) - 1 - i
                return

    def begin_scope(self):
        self.scopes.append({})

    def end_scope(self):
        self.scopes.pop()

    def declare(self, name):
        if not self.scopes:
            return
        scope = self.scopes[-1]
        if name.lexeme in scope:
            self.error("Already a variable with this name in this scope.")
        scope[name.lexeme] = False

    def define(self, name):
        if not self.scopes:
            return
        self.scopes[-1][name.lexeme] = True

    def error(self, message):
        print(f"Error: {message}", file=sys.stderr)
        self.had_error = True
