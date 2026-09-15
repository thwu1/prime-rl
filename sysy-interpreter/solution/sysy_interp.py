#!/usr/bin/env python3
"""SysY language interpreter."""

import sys

# ======================== Control Flow Signals ========================

class BreakSignal(Exception):
    pass

class ContinueSignal(Exception):
    pass

class ReturnSignal(Exception):
    def __init__(self, value=0):
        self.value = value

# ======================== Lexer ========================

KEYWORDS = frozenset(
    ["const", "int", "void", "if", "else", "while", "break", "continue", "return"]
)


def lex(source):
    """Tokenize SysY source into a list of (type, value, line) tuples."""
    tokens = []
    i = 0
    line = 1
    n = len(source)

    while i < n:
        c = source[i]

        # Whitespace
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            line += 1
            i += 1
            continue

        # Comments
        if c == "/" and i + 1 < n:
            if source[i + 1] == "/":
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if source[i + 1] == "*":
                i += 2
                while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                    if source[i] == "\n":
                        line += 1
                    i += 1
                i += 2
                continue

        # Numbers
        if c.isdigit():
            start = i
            if c == "0" and i + 1 < n and source[i + 1] in "xX":
                # Hexadecimal
                i += 2
                while i < n and source[i] in "0123456789abcdefABCDEF":
                    i += 1
                tokens.append(("INT", int(source[start:i], 16), line))
            elif c == "0" and i + 1 < n and source[i + 1] in "01234567":
                # Octal
                while i < n and source[i] in "01234567":
                    i += 1
                tokens.append(("INT", int(source[start:i], 8), line))
            else:
                # Decimal (or bare 0)
                while i < n and source[i].isdigit():
                    i += 1
                tokens.append(("INT", int(source[start:i]), line))
            continue

        # Identifiers / keywords
        if c.isalpha() or c == "_":
            start = i
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            word = source[start:i]
            if word in KEYWORDS:
                tokens.append((word.upper(), word, line))
            else:
                tokens.append(("IDENT", word, line))
            continue

        # Two-character operators
        if i + 1 < n:
            two = source[i : i + 2]
            if two in ("<=", ">=", "==", "!=", "&&", "||"):
                tokens.append((two, two, line))
                i += 2
                continue

        # Single-character token
        tokens.append((c, c, line))
        i += 1

    tokens.append(("EOF", None, line))
    return tokens

# ======================== Parser ========================

class Parser:
    """Recursive-descent parser producing a dict-based AST."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, tp):
        t = self.advance()
        if t[0] != tp:
            raise SyntaxError(
                f"Expected {tp}, got {t[0]} ({t[1]!r}) at line {t[2]}"
            )
        return t

    def match(self, tp):
        if self.peek()[0] == tp:
            return self.advance()
        return None

    # ---- Top-level ----

    def parse_comp_unit(self):
        items = []
        while self.peek()[0] != "EOF":
            items.append(self._parse_decl_or_funcdef())
        return {"type": "CompUnit", "items": items}

    def _parse_decl_or_funcdef(self):
        if self.peek()[0] == "CONST":
            return self._parse_const_decl()
        save = self.pos
        type_tok = self.advance()  # INT or VOID
        if type_tok[1] == "void":
            name = self.expect("IDENT")
            self.expect("(")
            params = self._parse_func_params()
            self.expect(")")
            body = self._parse_block()
            return {
                "type": "FuncDef",
                "ret_type": "void",
                "name": name[1],
                "params": params,
                "body": body,
            }
        # int — could be func def or var decl
        name = self.expect("IDENT")
        if self.peek()[0] == "(":
            self.expect("(")
            params = self._parse_func_params()
            self.expect(")")
            body = self._parse_block()
            return {
                "type": "FuncDef",
                "ret_type": "int",
                "name": name[1],
                "params": params,
                "body": body,
            }
        # Variable declaration — backtrack
        self.pos = save
        return self._parse_var_decl()

    # ---- Declarations ----

    def _parse_const_decl(self):
        self.expect("CONST")
        self.expect("INT")
        defs = [self._parse_const_def()]
        while self.match(","):
            defs.append(self._parse_const_def())
        self.expect(";")
        return {"type": "ConstDecl", "defs": defs}

    def _parse_const_def(self):
        name = self.expect("IDENT")
        dims = []
        while self.match("["):
            dims.append(self._parse_exp())
            self.expect("]")
        self.expect("=")
        init = self._parse_const_init_val()
        return {"name": name[1], "dims": dims, "init": init}

    def _parse_const_init_val(self):
        if self.peek()[0] == "{":
            self.advance()
            if self.peek()[0] == "}":
                self.advance()
                return {"type": "InitList", "items": []}
            items = [self._parse_const_init_val()]
            while self.match(","):
                items.append(self._parse_const_init_val())
            self.expect("}")
            return {"type": "InitList", "items": items}
        return self._parse_exp()

    def _parse_var_decl(self):
        self.expect("INT")
        defs = [self._parse_var_def()]
        while self.match(","):
            defs.append(self._parse_var_def())
        self.expect(";")
        return {"type": "VarDecl", "defs": defs}

    def _parse_var_def(self):
        name = self.expect("IDENT")
        dims = []
        while self.match("["):
            dims.append(self._parse_exp())
            self.expect("]")
        init = None
        if self.match("="):
            init = self._parse_init_val()
        return {"name": name[1], "dims": dims, "init": init}

    def _parse_init_val(self):
        if self.peek()[0] == "{":
            self.advance()
            if self.peek()[0] == "}":
                self.advance()
                return {"type": "InitList", "items": []}
            items = [self._parse_init_val()]
            while self.match(","):
                items.append(self._parse_init_val())
            self.expect("}")
            return {"type": "InitList", "items": items}
        return self._parse_exp()

    # ---- Functions ----

    def _parse_func_params(self):
        params = []
        if self.peek()[0] == "INT":
            params.append(self._parse_func_param())
            while self.match(","):
                params.append(self._parse_func_param())
        return params

    def _parse_func_param(self):
        self.expect("INT")
        name = self.expect("IDENT")
        dims = None
        if self.match("["):
            self.expect("]")
            dims = [None]
            while self.match("["):
                dims.append(self._parse_exp())
                self.expect("]")
        return {"name": name[1], "dims": dims}

    # ---- Statements ----

    def _parse_block(self):
        self.expect("{")
        items = []
        while self.peek()[0] != "}":
            items.append(self._parse_block_item())
        self.expect("}")
        return {"type": "Block", "items": items}

    def _parse_block_item(self):
        pk = self.peek()[0]
        if pk == "CONST":
            return self._parse_const_decl()
        if pk == "INT":
            # Distinguish var decl from expression-stmt starting with an
            # identifier that happens to look like 'int'.  INT is a keyword
            # so it can only begin a declaration here.
            return self._parse_var_decl()
        return self._parse_stmt()

    def _parse_stmt(self):
        pk = self.peek()[0]
        if pk == "{":
            return self._parse_block()
        if pk == "IF":
            return self._parse_if()
        if pk == "WHILE":
            return self._parse_while()
        if pk == "BREAK":
            self.advance()
            self.expect(";")
            return {"type": "Break"}
        if pk == "CONTINUE":
            self.advance()
            self.expect(";")
            return {"type": "Continue"}
        if pk == "RETURN":
            self.advance()
            val = None
            if self.peek()[0] != ";":
                val = self._parse_exp()
            self.expect(";")
            return {"type": "Return", "value": val}
        if pk == ";":
            self.advance()
            return {"type": "Empty"}
        # Expression statement or assignment
        exp = self._parse_exp()
        if self.match("="):
            rhs = self._parse_exp()
            self.expect(";")
            return {"type": "Assign", "target": exp, "value": rhs}
        self.expect(";")
        return {"type": "ExprStmt", "expr": exp}

    def _parse_if(self):
        self.expect("IF")
        self.expect("(")
        cond = self._parse_exp()
        self.expect(")")
        then = self._parse_stmt()
        els = None
        if self.match("ELSE"):
            els = self._parse_stmt()
        return {"type": "If", "cond": cond, "then": then, "else": els}

    def _parse_while(self):
        self.expect("WHILE")
        self.expect("(")
        cond = self._parse_exp()
        self.expect(")")
        body = self._parse_stmt()
        return {"type": "While", "cond": cond, "body": body}

    # ---- Expressions (operator precedence climbing) ----

    def _parse_exp(self):
        return self._parse_lor()

    def _parse_lor(self):
        left = self._parse_land()
        while self.peek()[0] == "||":
            self.advance()
            right = self._parse_land()
            left = {"type": "BinOp", "op": "||", "left": left, "right": right}
        return left

    def _parse_land(self):
        left = self._parse_eq()
        while self.peek()[0] == "&&":
            self.advance()
            right = self._parse_eq()
            left = {"type": "BinOp", "op": "&&", "left": left, "right": right}
        return left

    def _parse_eq(self):
        left = self._parse_rel()
        while self.peek()[0] in ("==", "!="):
            op = self.advance()
            right = self._parse_rel()
            left = {"type": "BinOp", "op": op[1], "left": left, "right": right}
        return left

    def _parse_rel(self):
        left = self._parse_add()
        while self.peek()[0] in ("<", ">", "<=", ">="):
            op = self.advance()
            right = self._parse_add()
            left = {"type": "BinOp", "op": op[1], "left": left, "right": right}
        return left

    def _parse_add(self):
        left = self._parse_mul()
        while self.peek()[0] in ("+", "-"):
            op = self.advance()
            right = self._parse_mul()
            left = {"type": "BinOp", "op": op[1], "left": left, "right": right}
        return left

    def _parse_mul(self):
        left = self._parse_unary()
        while self.peek()[0] in ("*", "/", "%"):
            op = self.advance()
            right = self._parse_unary()
            left = {"type": "BinOp", "op": op[1], "left": left, "right": right}
        return left

    def _parse_unary(self):
        pk = self.peek()
        if pk[0] in ("+", "-", "!"):
            op = self.advance()
            expr = self._parse_unary()
            return {"type": "UnaryOp", "op": op[1], "expr": expr}
        # Function call: IDENT (
        if (
            pk[0] == "IDENT"
            and self.pos + 1 < len(self.tokens)
            and self.tokens[self.pos + 1][0] == "("
        ):
            name = self.advance()
            self.expect("(")
            args = []
            if self.peek()[0] != ")":
                args.append(self._parse_exp())
                while self.match(","):
                    args.append(self._parse_exp())
            self.expect(")")
            return {"type": "FuncCall", "name": name[1], "args": args}
        return self._parse_primary()

    def _parse_primary(self):
        pk = self.peek()
        if pk[0] == "(":
            self.advance()
            exp = self._parse_exp()
            self.expect(")")
            return exp
        if pk[0] == "INT":
            self.advance()
            return {"type": "Number", "value": pk[1]}
        if pk[0] == "IDENT":
            name = self.advance()
            indices = []
            while self.peek()[0] == "[":
                self.advance()
                indices.append(self._parse_exp())
                self.expect("]")
            if indices:
                return {"type": "ArrayAccess", "name": name[1], "indices": indices}
            return {"type": "Var", "name": name[1]}
        raise SyntaxError(
            f"Unexpected token {pk[0]} ({pk[1]!r}) at line {pk[2]}"
        )


# ======================== Environment (scoping) ========================

class Env:
    __slots__ = ("parent", "vars")

    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}

    def define(self, name, value):
        self.vars[name] = value

    def lookup(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        raise RuntimeError(f"Undefined variable: {name}")

    def assign(self, name, value):
        if name in self.vars:
            self.vars[name] = value
            return
        if self.parent is not None:
            self.parent.assign(name, value)
            return
        raise RuntimeError(f"Undefined variable: {name}")


# ======================== Interpreter ========================

def _c_div(a, b):
    """Integer division truncating toward zero (C semantics)."""
    q = a // b
    if (a ^ b) < 0 and a % b != 0:
        q += 1
    return q


def _c_mod(a, b):
    """Integer modulo consistent with _c_div (C semantics)."""
    return a - _c_div(a, b) * b


class Interpreter:
    def __init__(self, program):
        self.program = program
        self.global_env = Env()
        self.functions = {}
        self._input_tokens = []

    # ---- Runtime library ----

    def _read_token(self):
        while not self._input_tokens:
            line = sys.stdin.readline()
            if not line:
                return None
            self._input_tokens.extend(line.split())
        return self._input_tokens.pop(0)

    def _rt_getint(self):
        tok = self._read_token()
        return int(tok) if tok is not None else 0

    def _rt_getch(self):
        ch = sys.stdin.read(1)
        return ord(ch) if ch else -1

    def _rt_getarray(self, arr_ref):
        n = self._rt_getint()
        for i in range(n):
            arr_ref["storage"][arr_ref["offset"] + i] = self._rt_getint()
        return n

    @staticmethod
    def _rt_putint(a):
        sys.stdout.write(str(a))

    @staticmethod
    def _rt_putch(a):
        sys.stdout.write(chr(a))

    @staticmethod
    def _rt_putarray(n, arr_ref):
        parts = []
        for i in range(n):
            parts.append(str(arr_ref["storage"][arr_ref["offset"] + i]))
        sys.stdout.write(f"{n}: " + " ".join(parts) + "\n")

    BUILTINS = {
        "getint", "getch", "getarray",
        "putint", "putch", "putarray",
        "starttime", "stoptime",
    }

    def _call_builtin(self, name, args):
        if name == "getint":
            return self._rt_getint()
        if name == "getch":
            return self._rt_getch()
        if name == "getarray":
            return self._rt_getarray(args[0])
        if name == "putint":
            self._rt_putint(args[0])
            return 0
        if name == "putch":
            self._rt_putch(args[0])
            return 0
        if name == "putarray":
            self._rt_putarray(args[0], args[1])
            return 0
        # starttime / stoptime — no-ops
        return 0

    # ---- Entry point ----

    def run(self):
        for item in self.program["items"]:
            if item["type"] == "FuncDef":
                self.functions[item["name"]] = item
            else:
                self._exec_decl(item, self.global_env, is_global=True)
        if "main" not in self.functions:
            raise RuntimeError("No main function defined")
        return self._call_func("main", [])

    # ---- Function calls ----

    def _call_func(self, name, args):
        if name in self.BUILTINS:
            return self._call_builtin(name, args)
        func = self.functions.get(name)
        if func is None:
            raise RuntimeError(f"Undefined function: {name}")
        env = Env(self.global_env)
        for i, param in enumerate(func["params"]):
            env.define(param["name"], args[i])
        try:
            self._exec_block(func["body"], env)
        except ReturnSignal as r:
            return r.value
        return 0

    # ---- Statement execution ----

    def _exec_block(self, block, parent_env):
        env = Env(parent_env)
        for item in block["items"]:
            self._exec_item(item, env)

    def _exec_item(self, node, env):
        tp = node["type"]
        if tp in ("VarDecl", "ConstDecl"):
            self._exec_decl(node, env)
        else:
            self._exec_stmt(node, env)

    def _exec_stmt(self, stmt, env):
        tp = stmt["type"]
        if tp == "Block":
            self._exec_block(stmt, env)
        elif tp == "Assign":
            val = self._eval(stmt["value"], env)
            self._assign_lval(stmt["target"], val, env)
        elif tp == "ExprStmt":
            self._eval(stmt["expr"], env)
        elif tp == "If":
            cond = self._eval(stmt["cond"], env)
            if cond:
                self._exec_stmt(stmt["then"], env)
            elif stmt["else"] is not None:
                self._exec_stmt(stmt["else"], env)
        elif tp == "While":
            while True:
                cond = self._eval(stmt["cond"], env)
                if not cond:
                    break
                try:
                    self._exec_stmt(stmt["body"], env)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif tp == "Break":
            raise BreakSignal()
        elif tp == "Continue":
            raise ContinueSignal()
        elif tp == "Return":
            val = 0
            if stmt["value"] is not None:
                val = self._eval(stmt["value"], env)
            raise ReturnSignal(val)
        elif tp == "Empty":
            pass

    # ---- Declarations ----

    def _exec_decl(self, decl, env, is_global=False):
        is_const = decl["type"] == "ConstDecl"
        for d in decl["defs"]:
            self._exec_def(d, env, is_const=is_const, is_global=is_global)

    def _exec_def(self, vdef, env, is_const=False, is_global=False):
        name = vdef["name"]
        dim_exprs = vdef.get("dims", [])
        if dim_exprs:
            # Array
            dims = [self._eval(d, env) for d in dim_exprs]
            total = 1
            for d in dims:
                total *= d
            storage = [0] * total
            if vdef.get("init") is not None:
                self._init_array(storage, 0, dims, vdef["init"], env)
            env.define(name, {"storage": storage, "offset": 0, "dims": dims})
        else:
            # Scalar
            if vdef.get("init") is not None:
                val = self._eval(vdef["init"], env)
            elif is_global:
                val = 0
            else:
                val = 0  # undefined in spec; default 0 for safety
            env.define(name, val)

    def _init_array(self, storage, offset, dims, init, env):
        """Recursively initialize array storage from an InitList or scalar."""
        if init["type"] != "InitList":
            # Single scalar for a (degenerate) array
            storage[offset] = self._eval(init, env)
            return
        self._fill_array(storage, offset, dims, init["items"], env)

    def _fill_array(self, storage, offset, dims, items, env):
        """Handle brace-elision initialization for multi-dimensional arrays."""
        if not dims:
            return
        if len(dims) == 1:
            # Base case: 1-D fill
            for idx, item in enumerate(items):
                if idx >= dims[0]:
                    break
                if item.get("type") == "InitList":
                    # Shouldn't normally happen at 1-D level, but handle it
                    if item["items"]:
                        storage[offset + idx] = self._eval(item["items"][0], env)
                else:
                    storage[offset + idx] = self._eval(item, env)
            return

        sub_size = 1
        for d in dims[1:]:
            sub_size *= d

        pos = 0  # which sub-array we're filling
        i = 0  # index into items
        while i < len(items) and pos < dims[0]:
            item = items[i]
            if item.get("type") == "InitList":
                # This InitList fills one complete sub-array
                self._fill_array(
                    storage, offset + pos * sub_size, dims[1:], item["items"], env
                )
                pos += 1
                i += 1
            else:
                # Brace elision: consecutive scalars fill the current sub-array
                slot = 0
                while (
                    i < len(items)
                    and slot < sub_size
                    and items[i].get("type") != "InitList"
                ):
                    storage[offset + pos * sub_size + slot] = self._eval(
                        items[i], env
                    )
                    slot += 1
                    i += 1
                pos += 1

    # ---- LVal assignment ----

    def _assign_lval(self, lval, value, env):
        tp = lval["type"]
        if tp == "Var":
            env.assign(lval["name"], value)
        elif tp == "ArrayAccess":
            arr = env.lookup(lval["name"])
            flat = arr["offset"]
            indices = [self._eval(idx, env) for idx in lval["indices"]]
            dims = arr["dims"]
            for k, ix in enumerate(indices):
                stride = 1
                for d in dims[k + 1 :]:
                    stride *= d
                flat += ix * stride
            arr["storage"][flat] = value
        else:
            raise RuntimeError(f"Invalid assignment target: {tp}")

    # ---- Expression evaluation ----

    def _eval(self, exp, env):
        tp = exp["type"]

        if tp == "Number":
            return exp["value"]

        if tp == "Var":
            return env.lookup(exp["name"])

        if tp == "ArrayAccess":
            arr = env.lookup(exp["name"])
            indices = [self._eval(idx, env) for idx in exp["indices"]]
            dims = arr["dims"]
            if len(indices) < len(dims):
                # Partial indexing → sub-array reference
                new_offset = arr["offset"]
                for k, ix in enumerate(indices):
                    stride = 1
                    for d in dims[k + 1 :]:
                        stride *= d
                    new_offset += ix * stride
                return {
                    "storage": arr["storage"],
                    "offset": new_offset,
                    "dims": dims[len(indices) :],
                }
            # Full indexing → scalar
            flat = arr["offset"]
            for k, ix in enumerate(indices):
                stride = 1
                for d in dims[k + 1 :]:
                    stride *= d
                flat += ix * stride
            return arr["storage"][flat]

        if tp == "BinOp":
            op = exp["op"]
            # Short-circuit operators
            if op == "&&":
                left = self._eval(exp["left"], env)
                if left == 0:
                    return 0
                right = self._eval(exp["right"], env)
                return 1 if right != 0 else 0
            if op == "||":
                left = self._eval(exp["left"], env)
                if left != 0:
                    return 1
                right = self._eval(exp["right"], env)
                return 1 if right != 0 else 0
            left = self._eval(exp["left"], env)
            right = self._eval(exp["right"], env)
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                return _c_div(left, right)
            if op == "%":
                return _c_mod(left, right)
            if op == "<":
                return 1 if left < right else 0
            if op == ">":
                return 1 if left > right else 0
            if op == "<=":
                return 1 if left <= right else 0
            if op == ">=":
                return 1 if left >= right else 0
            if op == "==":
                return 1 if left == right else 0
            if op == "!=":
                return 1 if left != right else 0
            raise RuntimeError(f"Unknown binary op: {op}")

        if tp == "UnaryOp":
            val = self._eval(exp["expr"], env)
            op = exp["op"]
            if op == "-":
                return -val
            if op == "+":
                return val
            if op == "!":
                return 1 if val == 0 else 0
            raise RuntimeError(f"Unknown unary op: {op}")

        if tp == "FuncCall":
            name = exp["name"]
            args = [self._eval(a, env) for a in exp["args"]]
            return self._call_func(name, args)

        raise RuntimeError(f"Cannot evaluate node type: {tp}")


# ======================== Main ========================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_interp <file.sy>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    # Strip preprocessor directives
    source = "\n".join(
        line for line in source.split("\n") if not line.lstrip().startswith("#")
    )

    tokens = lex(source)
    parser = Parser(tokens)
    program = parser.parse_comp_unit()
    interp = Interpreter(program)
    ret = interp.run()
    sys.stdout.flush()
    sys.exit(ret % 256)


if __name__ == "__main__":
    main()
