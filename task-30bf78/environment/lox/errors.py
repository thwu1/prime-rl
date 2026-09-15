class LoxError(Exception):
    pass


class LoxRuntimeError(LoxError):
    def __init__(self, token, message):
        self.token = token
        self.message = message
        super().__init__(message)


class LoxParseError(LoxError):
    def __init__(self, token, message):
        self.token = token
        self.message = message
        super().__init__(message)


class LoxSemanticError(LoxError):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


class ReturnException(Exception):
    def __init__(self, value):
        self.value = value
