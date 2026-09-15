"""
ANF Lambda Calculus - AST definitions and S-expression parser.

Grammar (A-Normal Form):

  aexp ::= (lambda (var ...) exp)   -- lambda abstraction
         | var                       -- variable reference
         | integer                   -- integer literal
         | #t | #f                   -- boolean literals
         | (prim aexp ...)           -- primitive operation (prim in {+,-,*,=,<})

  cexp ::= (aexp aexp ...)           -- function application
         | (if aexp exp exp)         -- conditional
         | (call/cc aexp)            -- first-class continuation capture
         | (set! var aexp)           -- mutation
         | (letrec ((var aexp) ...) exp)  -- recursive binding

  exp  ::= (let ((var exp)) exp)     -- let binding (single)
         | aexp                      -- atomic expression
         | cexp                      -- complex expression

Lambda labels are assigned in pre-order (declaration order) starting from 1,
reset on each call to parse().
"""


_label_counter = 0

def _fresh_label():
    global _label_counter
    _label_counter += 1
    return _label_counter


# ============================================================
# AST Node Classes
# ============================================================

class Exp:
    """Base class for all expressions."""
    pass


# --- Atomic Expressions ---

class Lam(Exp):
    """Lambda abstraction: (lambda (params...) body)"""
    def __init__(self, params, body, label=None):
        self.params = tuple(params)
        self.body = body
        if label is not None:
            self.label = label
        else:
            self.label = _fresh_label()

    def __repr__(self):
        return f"Lam#{self.label}({', '.join(self.params)})"

    def __eq__(self, other):
        return isinstance(other, Lam) and self.label == other.label

    def __hash__(self):
        return hash(('Lam', self.label))


class Var(Exp):
    """Variable reference."""
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Var({self.name})"

    def __eq__(self, other):
        return isinstance(other, Var) and self.name == other.name

    def __hash__(self):
        return hash(('Var', self.name))


class IntLit(Exp):
    """Integer literal."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Int({self.value})"


class BoolLit(Exp):
    """Boolean literal: #t or #f."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Bool({self.value})"


class PrimOp(Exp):
    """Primitive operation: (+ x y), (= a b), (< a b), etc."""
    def __init__(self, op, args):
        self.op = op
        self.args = tuple(args)

    def __repr__(self):
        return f"Prim({self.op}, {self.args})"


# --- Complex Expressions ---

class App(Exp):
    """Function application: (f arg1 arg2 ...)"""
    def __init__(self, func, args):
        self.func = func
        self.args = tuple(args)

    def __repr__(self):
        return f"App({self.func}, {self.args})"


class If(Exp):
    """Conditional: (if cond then_exp else_exp)"""
    def __init__(self, cond, then_exp, else_exp):
        self.cond = cond
        self.then_exp = then_exp
        self.else_exp = else_exp

    def __repr__(self):
        return f"If({self.cond}, ...)"


class CallCC(Exp):
    """First-class continuation capture: (call/cc f)"""
    def __init__(self, func):
        self.func = func

    def __repr__(self):
        return f"CallCC({self.func})"


class SetBang(Exp):
    """Mutation: (set! var val)"""
    def __init__(self, var, val):
        self.var = var
        self.val = val

    def __repr__(self):
        return f"Set!({self.var}, {self.val})"


class Letrec(Exp):
    """Recursive binding: (letrec ((v1 e1) (v2 e2) ...) body)"""
    def __init__(self, bindings, body):
        self.bindings = tuple(bindings)  # tuple of (name_str, Exp) pairs
        self.body = body

    def __repr__(self):
        return f"Letrec({[n for n, _ in self.bindings]}, ...)"


# --- Let Expression ---

class Let(Exp):
    """Let binding: (let ((var rhs)) body)"""
    def __init__(self, var, rhs, body):
        self.var = var
        self.rhs = rhs
        self.body = body

    def __repr__(self):
        return f"Let({self.var}, ...)"


# ============================================================
# S-Expression Parser
# ============================================================

PRIMITIVES = {'+', '-', '*', '=', '<'}


def tokenize(text):
    """Tokenize S-expression text into a list of string tokens."""
    tokens = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in ' \t\n\r':
            i += 1
        elif c == ';':
            while i < len(text) and text[i] != '\n':
                i += 1
        elif c == '(':
            tokens.append('(')
            i += 1
        elif c == ')':
            tokens.append(')')
            i += 1
        elif c == '#':
            if i + 1 < len(text) and text[i + 1] == 't':
                tokens.append('#t')
                i += 2
            elif i + 1 < len(text) and text[i + 1] == 'f':
                tokens.append('#f')
                i += 2
            else:
                raise SyntaxError(f"Unexpected '#' at position {i}")
        else:
            j = i
            while j < len(text) and text[j] not in ' \t\n\r()':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _parse_sexp(tokens, pos):
    """Parse tokens starting at pos into a nested list. Returns (sexp, new_pos)."""
    if pos >= len(tokens):
        raise SyntaxError("Unexpected end of input")

    if tokens[pos] == '(':
        result = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ')':
            elem, pos = _parse_sexp(tokens, pos)
            result.append(elem)
        if pos >= len(tokens):
            raise SyntaxError("Missing closing parenthesis")
        pos += 1  # skip ')'
        return result, pos
    else:
        return tokens[pos], pos + 1


def sexp_to_ast(sexp):
    """Convert a parsed S-expression (nested lists/strings) into an AST node."""
    if isinstance(sexp, str):
        if sexp == '#t':
            return BoolLit(True)
        elif sexp == '#f':
            return BoolLit(False)
        else:
            try:
                return IntLit(int(sexp))
            except ValueError:
                return Var(sexp)

    if not isinstance(sexp, list) or len(sexp) == 0:
        raise SyntaxError(f"Invalid expression: {sexp}")

    head = sexp[0]

    if head == 'lambda':
        if len(sexp) != 3:
            raise SyntaxError(f"lambda requires params and body: {sexp}")
        label = _fresh_label()
        params = sexp[1]
        body = sexp_to_ast(sexp[2])
        return Lam(params, body, label)

    elif head == 'let':
        if len(sexp) != 3:
            raise SyntaxError(f"let requires bindings and body: {sexp}")
        bindings = sexp[1]
        if len(bindings) != 1:
            raise SyntaxError("ANF let must have exactly one binding")
        binding = bindings[0]
        var_name = binding[0]
        rhs = sexp_to_ast(binding[1])
        body = sexp_to_ast(sexp[2])
        return Let(var_name, rhs, body)

    elif head == 'letrec':
        if len(sexp) != 3:
            raise SyntaxError(f"letrec requires bindings and body: {sexp}")
        bindings = [(b[0], sexp_to_ast(b[1])) for b in sexp[1]]
        body = sexp_to_ast(sexp[2])
        return Letrec(bindings, body)

    elif head == 'if':
        if len(sexp) != 4:
            raise SyntaxError(f"if requires condition, then, else: {sexp}")
        return If(sexp_to_ast(sexp[1]), sexp_to_ast(sexp[2]), sexp_to_ast(sexp[3]))

    elif head == 'set!':
        if len(sexp) != 3:
            raise SyntaxError(f"set! requires variable and value: {sexp}")
        return SetBang(sexp[1], sexp_to_ast(sexp[2]))

    elif head == 'call/cc':
        if len(sexp) != 2:
            raise SyntaxError(f"call/cc requires one argument: {sexp}")
        return CallCC(sexp_to_ast(sexp[1]))

    elif head in PRIMITIVES:
        args = [sexp_to_ast(a) for a in sexp[1:]]
        return PrimOp(head, args)

    else:
        func = sexp_to_ast(sexp[0])
        args = [sexp_to_ast(a) for a in sexp[1:]]
        return App(func, args)


def parse(text):
    """Parse program text into an AST. Resets lambda labels to start from 1."""
    global _label_counter
    _label_counter = 0
    tokens = tokenize(text)
    sexp, pos = _parse_sexp(tokens, 0)
    return sexp_to_ast(sexp)
