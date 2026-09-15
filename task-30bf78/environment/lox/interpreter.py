import sys
from .tokens import TokenType
from .ast_nodes import (
    Literal, Grouping, Unary, Binary, Variable, Assign, Logical, Call,
    Get, Set, This, Super, ExpressionStmt, PrintStmt, VarStmt, BlockStmt,
    IfStmt, WhileStmt, FunctionStmt, ReturnStmt, ClassStmt,
)
from .environment import Environment
from .callable import LoxCallable, LoxFunction, LoxClass, LoxInstance, ClockFunction
from .errors import LoxRuntimeError, ReturnException


def format_number(n):
    if n == int(n):
        return str(int(n))
    return str(n)


class Interpreter:
    def __init__(self):
        self.globals = Environment()
        self.environment = self.globals
        self.locals = {}
        self.had_runtime_error = False
        self.globals.define("clock", ClockFunction())

    def interpret(self, statements):
        try:
            for stmt in statements:
                self.execute(stmt)
        except LoxRuntimeError as e:
            if hasattr(e, "token") and hasattr(e.token, "line"):
                print(f"{e.message}\n[line {e.token.line}]", file=sys.stderr)
            else:
                print(e.message, file=sys.stderr)
            self.had_runtime_error = True

    def execute(self, stmt):
        if isinstance(stmt, ExpressionStmt):
            self.evaluate(stmt.expression)

        elif isinstance(stmt, PrintStmt):
            value = self.evaluate(stmt.expression)
            print(self.stringify(value))

        elif isinstance(stmt, VarStmt):
            value = None
            if stmt.initializer is not None:
                value = self.evaluate(stmt.initializer)
            self.environment.define(stmt.name.lexeme, value)

        elif isinstance(stmt, BlockStmt):
            self.execute_block(stmt.statements, Environment(self.environment))

        elif isinstance(stmt, IfStmt):
            if self.is_truthy(self.evaluate(stmt.condition)):
                self.execute(stmt.then_branch)
            elif stmt.else_branch is not None:
                self.execute(stmt.else_branch)

        elif isinstance(stmt, WhileStmt):
            while self.is_truthy(self.evaluate(stmt.condition)):
                self.execute(stmt.body)

        elif isinstance(stmt, FunctionStmt):
            function = LoxFunction(stmt, self.environment)
            self.environment.define(stmt.name.lexeme, function)

        elif isinstance(stmt, ReturnStmt):
            value = None
            if stmt.value is not None:
                value = self.evaluate(stmt.value)
            raise ReturnException(value)

        elif isinstance(stmt, ClassStmt):
            superclass = None
            if stmt.superclass is not None:
                superclass = self.evaluate(stmt.superclass)
                if not isinstance(superclass, LoxClass):
                    raise LoxRuntimeError(
                        stmt.superclass.name, "Superclass must be a class."
                    )

            self.environment.define(stmt.name.lexeme, None)

            if superclass is not None:
                self.environment = Environment(self.environment)
                self.environment.define("super", superclass)

            methods = {}
            for method in stmt.methods:
                is_init = method.name.lexeme == "init"
                function = LoxFunction(method, self.environment, is_init)
                methods[method.name.lexeme] = function

            klass = LoxClass(stmt.name.lexeme, superclass, methods)

            if superclass is not None:
                self.environment = self.environment.enclosing

            self.environment.assign(stmt.name, klass)

    def execute_block(self, statements, environment):
        previous = self.environment
        try:
            self.environment = environment
            for stmt in statements:
                self.execute(stmt)
        finally:
            self.environment = previous

    def evaluate(self, expr):
        if isinstance(expr, Literal):
            return expr.value

        elif isinstance(expr, Grouping):
            return self.evaluate(expr.expression)

        elif isinstance(expr, Unary):
            right = self.evaluate(expr.right)
            if expr.operator.ttype == TokenType.MINUS:
                self.check_number_operand(expr.operator, right)
                return -float(right)
            elif expr.operator.ttype == TokenType.BANG:
                return not self.is_truthy(right)

        elif isinstance(expr, Binary):
            left = self.evaluate(expr.left)
            right = self.evaluate(expr.right)
            op = expr.operator.ttype

            if op == TokenType.MINUS:
                self.check_number_operands(expr.operator, left, right)
                return float(left) - float(right)
            elif op == TokenType.PLUS:
                if isinstance(left, float) and isinstance(right, float):
                    return left + right
                if isinstance(left, str) and isinstance(right, str):
                    return left + right
                raise LoxRuntimeError(
                    expr.operator,
                    "Operands must be two numbers or two strings.",
                )
            elif op == TokenType.SLASH:
                self.check_number_operands(expr.operator, left, right)
                return float(left) / float(right)
            elif op == TokenType.STAR:
                self.check_number_operands(expr.operator, left, right)
                return float(left) * float(right)
            elif op == TokenType.GREATER:
                self.check_number_operands(expr.operator, left, right)
                return float(left) > float(right)
            elif op == TokenType.GREATER_EQUAL:
                self.check_number_operands(expr.operator, left, right)
                return float(left) >= float(right)
            elif op == TokenType.LESS:
                self.check_number_operands(expr.operator, left, right)
                return float(left) < float(right)
            elif op == TokenType.LESS_EQUAL:
                self.check_number_operands(expr.operator, left, right)
                return float(left) <= float(right)
            elif op == TokenType.BANG_EQUAL:
                return not self.is_equal(left, right)
            elif op == TokenType.EQUAL_EQUAL:
                return self.is_equal(left, right)

        elif isinstance(expr, Variable):
            return self.look_up_variable(expr.name, expr)

        elif isinstance(expr, Assign):
            value = self.evaluate(expr.value)
            distance = self.locals.get(id(expr))
            if distance is not None:
                self.environment.assign_at(distance, expr.name.lexeme, value)
            else:
                self.globals.assign(expr.name, value)
            return value

        elif isinstance(expr, Logical):
            left = self.evaluate(expr.left)
            if expr.operator.ttype == TokenType.OR:
                if self.is_truthy(left):
                    return left
            elif expr.operator.ttype == TokenType.AND:
                if not self.is_truthy(left):
                    return left
            return self.evaluate(expr.right)

        elif isinstance(expr, Call):
            callee = self.evaluate(expr.callee)
            arguments = [self.evaluate(arg) for arg in expr.arguments]
            if not isinstance(callee, LoxCallable):
                raise LoxRuntimeError(
                    expr.paren, "Can only call functions and classes."
                )
            if callee.arity() != len(arguments):
                raise LoxRuntimeError(
                    expr.paren,
                    f"Expected {callee.arity()} arguments but got {len(arguments)}.",
                )
            return callee.call(self, arguments)

        elif isinstance(expr, Get):
            obj = self.evaluate(expr.obj)
            if isinstance(obj, LoxInstance):
                return obj.get(expr.name)
            raise LoxRuntimeError(expr.name, "Only instances have properties.")

        elif isinstance(expr, Set):
            obj = self.evaluate(expr.obj)
            if not isinstance(obj, LoxInstance):
                raise LoxRuntimeError(expr.name, "Only instances have fields.")
            value = self.evaluate(expr.value)
            obj.set(expr.name, value)
            return value

        elif isinstance(expr, This):
            return self.look_up_variable(expr.keyword, expr)

        elif isinstance(expr, Super):
            distance = self.locals.get(id(expr))
            superclass = self.environment.get_at(distance, "super")
            obj = self.environment.get_at(distance - 1, "this")
            method = superclass.find_method(expr.method.lexeme)
            if method is None:
                raise LoxRuntimeError(
                    expr.method,
                    f"Undefined property '{expr.method.lexeme}'.",
                )
            return method.bind(obj)

        return None

    def look_up_variable(self, name, expr):
        distance = self.locals.get(id(expr))
        if distance is not None:
            return self.environment.get_at(distance, name.lexeme)
        return self.globals.get(name)

    def set_locals(self, locals_map):
        self.locals = locals_map

    def is_truthy(self, value):
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        return True

    def is_equal(self, a, b):
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        if type(a) != type(b):
            return False
        return a == b

    def check_number_operand(self, operator, operand):
        if isinstance(operand, float):
            return
        raise LoxRuntimeError(operator, "Operand must be a number.")

    def check_number_operands(self, operator, left, right):
        if isinstance(left, float) and isinstance(right, float):
            return
        raise LoxRuntimeError(operator, "Operands must be numbers.")

    def stringify(self, value):
        if value is None:
            return "nil"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return format_number(value)
        return str(value)
