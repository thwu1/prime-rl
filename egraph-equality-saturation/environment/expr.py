"""Expression representation, S-expression parser, evaluator, and cost function."""


class Expr:
    """Base class for expressions."""
    pass


class Var(Expr):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Var({self.name!r})"

    def __eq__(self, other):
        return isinstance(other, Var) and self.name == other.name

    def __hash__(self):
        return hash(("var", self.name))


class Num(Expr):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Num({self.value})"

    def __eq__(self, other):
        return isinstance(other, Num) and self.value == other.value

    def __hash__(self):
        return hash(("num", self.value))


class BinOp(Expr):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"BinOp({self.op!r}, {self.left!r}, {self.right!r})"

    def __eq__(self, other):
        return (isinstance(other, BinOp) and self.op == other.op
                and self.left == other.left and self.right == other.right)

    def __hash__(self):
        return hash(("binop", self.op, self.left, self.right))


def _tokenize(s):
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c in '()':
            tokens.append(c)
            i += 1
        elif c == '?' or c.isalpha() or c == '_':
            j = i
            while j < len(s) and (s[j].isalnum() or s[j] in '?_'):
                j += 1
            tokens.append(s[i:j])
            i = j
        elif c.isdigit() or (c == '-' and i + 1 < len(s) and s[i + 1].isdigit()):
            j = i + 1
            while j < len(s) and s[j].isdigit():
                j += 1
            tokens.append(s[i:j])
            i = j
        else:
            tokens.append(c)
            i += 1
    return tokens


def _parse_tokens(tokens, pos):
    if tokens[pos] == '(':
        pos += 1
        op = tokens[pos]
        pos += 1
        left, pos = _parse_tokens(tokens, pos)
        right, pos = _parse_tokens(tokens, pos)
        assert tokens[pos] == ')', f"Expected ), got {tokens[pos]}"
        pos += 1
        return BinOp(op, left, right), pos
    else:
        tok = tokens[pos]
        try:
            return Num(int(tok)), pos + 1
        except ValueError:
            return Var(tok), pos + 1


def parse(s):
    """Parse S-expression string into Expr tree.

    Examples:
        parse("x")           -> Var("x")
        parse("42")          -> Num(42)
        parse("(+ x 1)")     -> BinOp("+", Var("x"), Num(1))
    """
    tokens = _tokenize(s.strip())
    expr, _ = _parse_tokens(tokens, 0)
    return expr


def to_sexp(expr):
    """Convert Expr tree back to S-expression string."""
    if isinstance(expr, Num):
        return str(expr.value)
    elif isinstance(expr, Var):
        return expr.name
    elif isinstance(expr, BinOp):
        return f"({expr.op} {to_sexp(expr.left)} {to_sexp(expr.right)})"
    raise TypeError(f"Unknown expr type: {type(expr)}")


def expr_cost(expr):
    """Compute AST node count (each node costs 1)."""
    if isinstance(expr, (Num, Var)):
        return 1
    elif isinstance(expr, BinOp):
        return 1 + expr_cost(expr.left) + expr_cost(expr.right)
    raise TypeError(f"Unknown expr type: {type(expr)}")


def get_vars(expr):
    """Return set of variable names appearing in the expression."""
    if isinstance(expr, Var):
        return {expr.name}
    elif isinstance(expr, Num):
        return set()
    elif isinstance(expr, BinOp):
        return get_vars(expr.left) | get_vars(expr.right)
    return set()


def evaluate(expr, env):
    """Evaluate expression given variable bindings in env dict.

    Supports + and * operators.
    """
    if isinstance(expr, Num):
        return expr.value
    elif isinstance(expr, Var):
        return env[expr.name]
    elif isinstance(expr, BinOp):
        lv = evaluate(expr.left, env)
        rv = evaluate(expr.right, env)
        if expr.op == '+':
            return lv + rv
        elif expr.op == '*':
            return lv * rv
        raise ValueError(f"Unknown operator: {expr.op}")
    raise TypeError(f"Unknown expr type: {type(expr)}")
