#!/usr/bin/env python3
"""
MiniPratt Language Reference Implementation
Pratt (TDOP) parser with dynamic operator definitions and tree-walking evaluator.
"""

import sys


# ===== AST Nodes =====

class Num:
    __slots__ = ["value"]
    def __init__(self, value):
        self.value = value


class Var:
    __slots__ = ["name"]
    def __init__(self, name):
        self.name = name


class BinOp:
    __slots__ = ["op", "left", "right"]
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


class UnaryOp:
    __slots__ = ["op", "operand"]
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand


class TernaryExpr:
    __slots__ = ["cond", "then_expr", "else_expr"]
    def __init__(self, cond, then_expr, else_expr):
        self.cond = cond
        self.then_expr = then_expr
        self.else_expr = else_expr


class CallExpr:
    __slots__ = ["name", "args"]
    def __init__(self, name, args):
        self.name = name
        self.args = args


class LetExpr:
    __slots__ = ["name", "value", "body"]
    def __init__(self, name, value, body):
        self.name = name
        self.value = value
        self.body = body


class IfExpr:
    __slots__ = ["cond", "then_expr", "else_expr"]
    def __init__(self, cond, then_expr, else_expr):
        self.cond = cond
        self.then_expr = then_expr
        self.else_expr = else_expr


class FnDef:
    __slots__ = ["name", "params", "body"]
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body


class OpDef:
    __slots__ = ["fixity", "prec", "name", "params", "body"]
    def __init__(self, fixity, prec, name, params, body):
        self.fixity = fixity
        self.prec = prec
        self.name = name
        self.params = params
        self.body = body


class CustomBinOp:
    __slots__ = ["name", "left", "right"]
    def __init__(self, name, left, right):
        self.name = name
        self.left = left
        self.right = right


class CustomUnaryOp:
    __slots__ = ["name", "operand"]
    def __init__(self, name, operand):
        self.name = name
        self.operand = operand


# ===== Tokenizer =====

class Token:
    __slots__ = ["type", "value"]
    def __init__(self, type_, value):
        self.type = type_
        self.value = value
    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


KEYWORDS = {
    "let", "in", "if", "then", "else", "fn",
    "operator", "infixl", "infixr", "prefix",
}

TWO_CHAR_OPS = {"**", "==", "!=", "<=", ">=", "<<", ">>", "&&", "||"}

SINGLE_OP_CHARS = set("+-*/%<>&|^~!?")

PUNCT_CHARS = set("()=;,:")


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]

        if c in " \t\n\r":
            i += 1
            continue

        if c == "/" and i + 1 < n and source[i + 1] == "/":
            i += 2
            while i < n and source[i] != "\n":
                i += 1
            continue

        if c.isdigit():
            j = i + 1
            while j < n and source[j].isdigit():
                j += 1
            tokens.append(Token("NUM", int(source[i:j])))
            i = j
            continue

        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[i:j]
            if word == "true":
                tokens.append(Token("NUM", 1))
            elif word == "false":
                tokens.append(Token("NUM", 0))
            elif word in KEYWORDS:
                tokens.append(Token(word.upper(), word))
            else:
                tokens.append(Token("IDENT", word))
            i = j
            continue

        if i + 1 < n and source[i : i + 2] in TWO_CHAR_OPS:
            tokens.append(Token("OP", source[i : i + 2]))
            i += 2
            continue

        if c in SINGLE_OP_CHARS:
            tokens.append(Token("OP", c))
            i += 1
            continue

        if c in PUNCT_CHARS:
            tokens.append(Token(c, c))
            i += 1
            continue

        raise SyntaxError(f"Unexpected character: {c!r} at position {i}")

    tokens.append(Token("EOF", None))
    return tokens


# ===== Parser =====

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

        self.INFIX_OPS = {
            "||": (3, "left"),
            "&&": (4, "left"),
            "|":  (5, "left"),
            "^":  (6, "left"),
            "&":  (7, "left"),
            "==": (8, "left"), "!=": (8, "left"),
            "<":  (9, "left"), ">":  (9, "left"),
            "<=": (9, "left"), ">=": (9, "left"),
            "<<": (10, "left"), ">>": (10, "left"),
            "+":  (11, "left"), "-":  (11, "left"),
            "*":  (12, "left"), "/":  (12, "left"), "%": (12, "left"),
            "**": (14, "right"),
        }

        self.PREFIX_OPS = {"-": 13, "!": 13, "~": 13}

        self.custom_infix = {}
        self.custom_prefix = {}

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect_type(self, tp):
        tok = self.peek()
        if tok.type != tp:
            raise SyntaxError(f"Expected token type {tp}, got {tok}")
        return self.advance()

    def expect_value(self, val):
        tok = self.peek()
        if tok.value != val:
            raise SyntaxError(f"Expected {val!r}, got {tok}")
        return self.advance()

    def match_value(self, val):
        if self.peek().value == val:
            self.advance()
            return True
        return False

    # ---- program-level ----

    def parse_program(self):
        items = []
        while self.peek().type != "EOF":
            items.append(self._parse_toplevel())
            while self.peek().value == ";":
                self.advance()
        return items

    def _parse_toplevel(self):
        tok = self.peek()
        if tok.type == "FN":
            return self._parse_fn_def()
        if tok.type == "OPERATOR":
            return self._parse_op_def()
        return self._parse_expr(0)

    def _parse_fn_def(self):
        self.expect_type("FN")
        name = self.expect_type("IDENT").value
        self.expect_value("(")
        params = self._parse_param_list()
        self.expect_value(")")
        self.expect_value("=")
        body = self._parse_expr(0)
        return FnDef(name, params, body)

    def _parse_op_def(self):
        self.expect_type("OPERATOR")
        fixity = self.advance().value  # infixl | infixr | prefix
        prec = self.expect_type("NUM").value
        name = self.expect_type("IDENT").value
        self.expect_value("(")
        params = self._parse_param_list()
        self.expect_value(")")
        self.expect_value("=")
        body = self._parse_expr(0)

        if fixity in ("infixl", "infixr"):
            assoc = "left" if fixity == "infixl" else "right"
            self.custom_infix[name] = (prec, assoc)
        elif fixity == "prefix":
            self.custom_prefix[name] = prec

        return OpDef(fixity, prec, name, params, body)

    def _parse_param_list(self):
        params = []
        if self.peek().type == "IDENT":
            params.append(self.advance().value)
            while self.match_value(","):
                params.append(self.expect_type("IDENT").value)
        return params

    # ---- expressions (Pratt core) ----

    def _infix_bp(self, tok):
        if tok.type == "OP" and tok.value in self.INFIX_OPS:
            return self.INFIX_OPS[tok.value][0]
        if tok.type == "IDENT" and tok.value in self.custom_infix:
            return self.custom_infix[tok.value][0]
        if tok.type == "OP" and tok.value == "?":
            return 2
        if tok.value == "(":
            return 16
        return -1

    def _parse_expr(self, min_bp):
        left = self._parse_nud()

        while True:
            tok = self.peek()
            bp = self._infix_bp(tok)
            if bp < min_bp:
                break

            if tok.type == "OP" and tok.value == "?":
                self.advance()
                mid = self._parse_expr(0)
                self.expect_value(":")
                right = self._parse_expr(2)
                left = TernaryExpr(left, mid, right)

            elif tok.value == "(" and isinstance(left, Var):
                self.advance()
                args = []
                if self.peek().value != ")":
                    args.append(self._parse_expr(0))
                    while self.match_value(","):
                        args.append(self._parse_expr(0))
                self.expect_value(")")
                left = CallExpr(left.name, args)

            elif tok.type == "OP" and tok.value in self.INFIX_OPS:
                prec, assoc = self.INFIX_OPS[tok.value]
                self.advance()
                next_bp = prec + 1 if assoc == "left" else prec
                right = self._parse_expr(next_bp)
                left = BinOp(tok.value, left, right)

            elif tok.type == "IDENT" and tok.value in self.custom_infix:
                prec, assoc = self.custom_infix[tok.value]
                self.advance()
                next_bp = prec + 1 if assoc == "left" else prec
                right = self._parse_expr(next_bp)
                left = CustomBinOp(tok.value, left, right)

            else:
                break

        return left

    def _parse_nud(self):
        tok = self.peek()

        if tok.type == "OP" and tok.value in self.PREFIX_OPS:
            self.advance()
            operand = self._parse_expr(self.PREFIX_OPS[tok.value])
            return UnaryOp(tok.value, operand)

        if tok.type == "IDENT" and tok.value in self.custom_prefix:
            self.advance()
            operand = self._parse_expr(self.custom_prefix[tok.value])
            return CustomUnaryOp(tok.value, operand)

        if tok.type == "NUM":
            self.advance()
            return Num(tok.value)

        if tok.type == "IDENT":
            self.advance()
            return Var(tok.value)

        if tok.value == "(":
            self.advance()
            expr = self._parse_expr(0)
            self.expect_value(")")
            return expr

        if tok.type == "LET":
            self.advance()
            name = self.expect_type("IDENT").value
            self.expect_value("=")
            value = self._parse_expr(0)
            self.expect_type("IN")
            body = self._parse_expr(0)
            return LetExpr(name, value, body)

        if tok.type == "IF":
            self.advance()
            cond = self._parse_expr(0)
            self.expect_type("THEN")
            then_expr = self._parse_expr(0)
            self.expect_type("ELSE")
            else_expr = self._parse_expr(0)
            return IfExpr(cond, then_expr, else_expr)

        raise SyntaxError(f"Unexpected token in expression: {tok}")


# ===== Evaluator =====

class Env:
    __slots__ = ["bindings", "parent"]
    def __init__(self, parent=None):
        self.bindings = {}
        self.parent = parent

    def get(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.get(name)
        raise NameError(f"Undefined variable: {name}")

    def set(self, name, value):
        self.bindings[name] = value


def _div_trunc(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return int(a / b)


def _mod_trunc(a, b):
    if b == 0:
        raise ZeroDivisionError("modulo by zero")
    return a - _div_trunc(a, b) * b


class Evaluator:
    def __init__(self):
        self.functions = {}
        self.operators = {}
        self.global_env = Env()

    def run_program(self, items):
        for item in items:
            if isinstance(item, FnDef):
                self.functions[item.name] = (item.params, item.body)
            elif isinstance(item, OpDef):
                self.operators[item.name] = (item.params, item.body)

        result = 0
        for item in items:
            if not isinstance(item, (FnDef, OpDef)):
                result = self._eval(item, self.global_env)
        return result

    def _eval(self, node, env):
        if isinstance(node, Num):
            return node.value

        if isinstance(node, Var):
            return env.get(node.name)

        if isinstance(node, BinOp):
            return self._eval_binop(node, env)

        if isinstance(node, UnaryOp):
            val = self._eval(node.operand, env)
            if node.op == "-":
                return -val
            if node.op == "!":
                return 1 if val == 0 else 0
            if node.op == "~":
                return ~val
            raise RuntimeError(f"Unknown unary op: {node.op}")

        if isinstance(node, TernaryExpr):
            cond = self._eval(node.cond, env)
            return self._eval(
                node.then_expr if cond != 0 else node.else_expr, env
            )

        if isinstance(node, CallExpr):
            if node.name not in self.functions:
                raise NameError(f"Undefined function: {node.name}")
            params, body = self.functions[node.name]
            if len(node.args) != len(params):
                raise TypeError(
                    f"{node.name} expects {len(params)} args, "
                    f"got {len(node.args)}"
                )
            arg_vals = [self._eval(a, env) for a in node.args]
            fn_env = Env(self.global_env)
            for p, v in zip(params, arg_vals):
                fn_env.set(p, v)
            return self._eval(body, fn_env)

        if isinstance(node, LetExpr):
            val = self._eval(node.value, env)
            new_env = Env(env)
            new_env.set(node.name, val)
            return self._eval(node.body, new_env)

        if isinstance(node, IfExpr):
            cond = self._eval(node.cond, env)
            return self._eval(
                node.then_expr if cond != 0 else node.else_expr, env
            )

        if isinstance(node, CustomBinOp):
            if node.name not in self.operators:
                raise NameError(f"Undefined operator: {node.name}")
            params, body = self.operators[node.name]
            lv = self._eval(node.left, env)
            rv = self._eval(node.right, env)
            op_env = Env(self.global_env)
            op_env.set(params[0], lv)
            op_env.set(params[1], rv)
            return self._eval(body, op_env)

        if isinstance(node, CustomUnaryOp):
            if node.name not in self.operators:
                raise NameError(f"Undefined operator: {node.name}")
            params, body = self.operators[node.name]
            val = self._eval(node.operand, env)
            op_env = Env(self.global_env)
            op_env.set(params[0], val)
            return self._eval(body, op_env)

        raise RuntimeError(f"Unknown AST node: {type(node).__name__}")

    def _eval_binop(self, node, env):
        op = node.op
        left = self._eval(node.left, env)

        if op == "&&":
            return 1 if (left != 0 and self._eval(node.right, env) != 0) else 0
        if op == "||":
            return 1 if (left != 0 or self._eval(node.right, env) != 0) else 0

        right = self._eval(node.right, env)

        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return _div_trunc(left, right)
        if op == "%":
            return _mod_trunc(left, right)
        if op == "**":
            return left ** right
        if op == "<<":
            return left << right
        if op == ">>":
            return left >> right
        if op == "&":
            return left & right
        if op == "|":
            return left | right
        if op == "^":
            return left ^ right
        if op == "==":
            return 1 if left == right else 0
        if op == "!=":
            return 1 if left != right else 0
        if op == "<":
            return 1 if left < right else 0
        if op == ">":
            return 1 if left > right else 0
        if op == "<=":
            return 1 if left <= right else 0
        if op == ">=":
            return 1 if left >= right else 0

        raise RuntimeError(f"Unknown binary op: {op}")


# ===== Driver =====

def run(source):
    tokens = tokenize(source)
    parser = Parser(tokens)
    items = parser.parse_program()
    evaluator = Evaluator()
    return evaluator.run_program(items)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file.mp>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    print(run(source))
