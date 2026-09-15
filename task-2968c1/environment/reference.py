"""
MiniCalc: A small calculator language supporting arithmetic, variables,
string operations, and comparisons. (Reference implementation)
"""


class CalcError(Exception):
    """Error raised by the MiniCalc interpreter."""
    pass


def tokenize(source):
    """Convert source string into a list of (type, value) tokens."""
    tokens = []
    i = 0
    while i < len(source):
        ch = source[i]

        if ch in ' \t\r\n':
            i += 1
            continue

        if ch.isdigit():
            j = i
            has_dot = False
            while j < len(source) and (source[j].isdigit() or source[j] == '.'):
                if source[j] == '.':
                    if has_dot:
                        break
                    has_dot = True
                j += 1
            num_str = source[i:j]
            if has_dot:
                tokens.append(('NUM', float(num_str)))
            else:
                tokens.append(('NUM', int(num_str)))
            i = j
            continue

        if ch == '"':
            i += 1
            parts = []
            while i < len(source) and source[i] != '"':
                if source[i] == '\\' and i + 1 < len(source):
                    i += 1
                    esc = source[i]
                    if esc == 'n':
                        parts.append('\n')
                    elif esc == 't':
                        parts.append('\t')
                    elif esc == '\\':
                        parts.append('\\')
                    elif esc == '"':
                        parts.append('"')
                    else:
                        parts.append(esc)
                else:
                    parts.append(source[i])
                i += 1
            if i >= len(source):
                raise CalcError("Unterminated string literal")
            i += 1
            tokens.append(('STR', ''.join(parts)))
            continue

        if ch.isalpha() or ch == '_':
            j = i
            while j < len(source) and (source[j].isalnum() or source[j] == '_'):
                j += 1
            tokens.append(('ID', source[i:j]))
            i = j
            continue

        if i + 1 < len(source):
            two = source[i:i + 2]
            if two in ('==', '!=', '<=', '>='):
                tokens.append(('OP', two))
                i += 2
                continue

        if ch in '+-*/%=<>(),;':
            tokens.append(('OP', ch))
            i += 1
            continue

        raise CalcError(f"Unexpected character: '{ch}'")

    return tokens


class Evaluator:
    """Evaluate MiniCalc programs from a token stream."""

    def __init__(self):
        self.variables = {}
        self.output = []
        self.pos = 0
        self.tokens = []

    def run(self, source):
        """Tokenize and evaluate source. Return output as newline-joined string."""
        self.tokens = tokenize(source)
        self.pos = 0
        self.output = []

        while self.pos < len(self.tokens):
            self._statement()
            if self.pos < len(self.tokens) and self._peek() == ('OP', ';'):
                self.pos += 1

        return '\n'.join(str(v) for v in self.output)

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _statement(self):
        tok = self._peek()
        if tok is None:
            return

        if (tok[0] == 'ID' and
                self.pos + 1 < len(self.tokens) and
                self.tokens[self.pos + 1] == ('OP', '=')):
            name = tok[1]
            self.pos += 2
            self.variables[name] = self._expr()
            return

        if tok == ('ID', 'print'):
            self.pos += 1
            if self._peek() == ('OP', '('):
                self.pos += 1
                val = self._expr()
                if self._peek() == ('OP', ')'):
                    self.pos += 1
            else:
                val = self._expr()
            self.output.append(val)
            return

        self._expr()

    def _expr(self):
        return self._comparison()

    def _comparison(self):
        left = self._addition()
        while (self._peek() is not None and
               self._peek()[0] == 'OP' and
               self._peek()[1] in ('==', '!=', '<', '>', '<=', '>=')):
            op = self._peek()[1]
            self.pos += 1
            right = self._addition()
            left = self._do_compare(op, left, right)
        return left

    def _addition(self):
        left = self._multiplication()
        while (self._peek() is not None and
               self._peek()[0] == 'OP' and
               self._peek()[1] in ('+', '-')):
            op = self._peek()[1]
            self.pos += 1
            right = self._multiplication()
            if op == '+':
                if isinstance(left, str) or isinstance(right, str):
                    left = str(left) + str(right)
                else:
                    left = left + right
            else:
                left = left - right
        return left

    def _multiplication(self):
        left = self._unary()
        while (self._peek() is not None and
               self._peek()[0] == 'OP' and
               self._peek()[1] in ('*', '/', '%')):
            op = self._peek()[1]
            self.pos += 1
            right = self._unary()
            if op == '*':
                left = left * right
            elif op == '/':
                if right == 0:
                    raise CalcError("Division by zero")
                left = left / right
            elif op == '%':
                if right == 0:
                    raise CalcError("Modulo by zero")
                left = left % right
        return left

    def _unary(self):
        if self._peek() is not None and self._peek() == ('OP', '-'):
            self.pos += 1
            return -self._unary()
        return self._primary()

    def _primary(self):
        tok = self._peek()
        if tok is None:
            raise CalcError("Unexpected end of input")

        if tok[0] == 'NUM':
            self.pos += 1
            return tok[1]

        if tok[0] == 'STR':
            self.pos += 1
            return tok[1]

        if tok[0] == 'ID':
            name = tok[1]
            if name in ('true', 'false'):
                self.pos += 1
                return name == 'true'
            if name in ('len', 'abs', 'int', 'str', 'max', 'min'):
                return self._call_builtin(name)
            if name in self.variables:
                self.pos += 1
                return self.variables[name]
            raise CalcError(f"Undefined variable: {name}")

        if tok == ('OP', '('):
            self.pos += 1
            val = self._expr()
            if self._peek() == ('OP', ')'):
                self.pos += 1
            return val

        raise CalcError(f"Unexpected token: {tok}")

    def _call_builtin(self, name):
        self.pos += 1
        if self._peek() != ('OP', '('):
            raise CalcError(f"{name} requires parentheses")
        self.pos += 1

        args = []
        while self._peek() is not None and self._peek() != ('OP', ')'):
            args.append(self._expr())
            if self._peek() == ('OP', ','):
                self.pos += 1
        if self._peek() == ('OP', ')'):
            self.pos += 1

        if name == 'len':
            if len(args) != 1 or not isinstance(args[0], str):
                raise CalcError("len() takes 1 string argument")
            return len(args[0])
        if name == 'abs':
            if len(args) != 1:
                raise CalcError("abs() takes 1 argument")
            return abs(args[0])
        if name == 'int':
            return int(args[0])
        if name == 'str':
            return str(args[0])
        if name == 'max':
            return max(args)
        if name == 'min':
            return min(args)
        raise CalcError(f"Unknown function: {name}")

    def _do_compare(self, op, left, right):
        if op == '==':
            return left == right
        if op == '!=':
            return left != right
        if op == '<':
            return left < right
        if op == '>':
            return left > right
        if op == '<=':
            return left <= right
        if op == '>=':
            return left >= right
        raise CalcError(f"Unknown comparison: {op}")


def execute(source):
    """Execute MiniCalc source and return output string."""
    evaluator = Evaluator()
    return evaluator.run(source)
