import time
from .environment import Environment
from .errors import ReturnException


class LoxCallable:
    def call(self, interpreter, arguments):
        raise NotImplementedError

    def arity(self):
        raise NotImplementedError


class ClockFunction(LoxCallable):
    def call(self, interpreter, arguments):
        return float(time.time())

    def arity(self):
        return 0

    def __str__(self):
        return "<native fn>"


class LoxFunction(LoxCallable):
    def __init__(self, declaration, closure, is_initializer=False):
        self.declaration = declaration
        self.closure = closure
        self.is_initializer = is_initializer

    def call(self, interpreter, arguments):
        env = Environment(self.closure)
        for i, param in enumerate(self.declaration.params):
            env.define(param.lexeme, arguments[i])
        try:
            interpreter.execute_block(self.declaration.body, env)
        except ReturnException as ret:
            if self.is_initializer:
                return self.closure.get_at(0, "this")
            return ret.value
        if self.is_initializer:
            return self.closure.get_at(0, "this")
        return None

    def bind(self, instance):
        env = Environment(self.closure)
        env.define("this", instance)
        return LoxFunction(self.declaration, env, self.is_initializer)

    def arity(self):
        return len(self.declaration.params)

    def __str__(self):
        return f"<fn {self.declaration.name.lexeme}>"


class LoxClass(LoxCallable):
    def __init__(self, name, superclass, methods):
        self.name = name
        self.superclass = superclass
        self.methods = methods

    def call(self, interpreter, arguments):
        instance = LoxInstance(self)
        initializer = self.find_method("init")
        if initializer is not None:
            initializer.bind(instance).call(interpreter, arguments)
        return instance

    def arity(self):
        initializer = self.find_method("init")
        if initializer is not None:
            return initializer.arity()
        return 0

    def find_method(self, name):
        if name in self.methods:
            return self.methods[name]
        if self.superclass is not None:
            return self.superclass.find_method(name)
        return None

    def __str__(self):
        return self.name


class LoxInstance:
    def __init__(self, klass):
        self.klass = klass
        self.fields = {}

    def get(self, name):
        if name.lexeme in self.fields:
            return self.fields[name.lexeme]
        method = self.klass.find_method(name.lexeme)
        if method is not None:
            return method.bind(self)
        from .errors import LoxRuntimeError
        raise LoxRuntimeError(name, f"Undefined property '{name.lexeme}'.")

    def set(self, name, value):
        self.fields[name.lexeme] = value

    def __str__(self):
        return f"{self.klass.name} instance"
