def compose(*funcs):
    def composed(x):
        result = x
        for f in reversed(funcs):
            result = f(result)
        return result
    return composed
