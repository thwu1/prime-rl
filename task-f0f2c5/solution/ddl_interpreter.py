#!/usr/bin/env python3
"""DaeDaLus subset interpreter with flex-generated tokenizer via ctypes."""

import sys
import json
import struct
import ctypes
import os

# ============================================================
# Token class (used by Parser)
# ============================================================

class Token:
    __slots__ = ("ty", "val", "line", "col")
    def __init__(self, ty, val, line, col):
        self.ty = ty
        self.val = val
        self.line = line
        self.col = col
    def __repr__(self):
        return f"T({self.ty},{self.val!r},L{self.line}C{self.col})"


# ============================================================
# Flex tokenizer interface via ctypes
# ============================================================

# Token type constants — must match the C defines in ddl_lexer.l
TOK_EOF = 0
TOK_ID = 1
TOK_INT = 2
TOK_STR = 3
TOK_ARROW = 10
TOK_BIASED = 11
TOK_DOTDOT = 12
TOK_LBPIPE = 13
TOK_RBPIPE = 14
TOK_LE = 15
TOK_GE = 16
TOK_EQEQ = 17
TOK_DOLLARDOLLAR = 18
TOK_DOLLAR = 19
TOK_LP = 20
TOK_RP = 21
TOK_LB = 22
TOK_RB = 23
TOK_LC = 24
TOK_RC = 25
TOK_EQ = 26
TOK_DOT = 27
TOK_COL = 28
TOK_SEMI = 29
TOK_COMMA = 30
TOK_LT = 31
TOK_GT = 32
TOK_PLUS = 33
TOK_MINUS = 34
TOK_STAR = 35
TOK_AT = 36
TOK_CARET = 37
TOK_PIPE = 38


class DDLToken(ctypes.Structure):
    """Mirror of the C DDLToken struct for ctypes interop."""
    _fields_ = [
        ("type", ctypes.c_int),
        ("line", ctypes.c_int),
        ("col", ctypes.c_int),
        ("int_val", ctypes.c_longlong),
        ("str_val", ctypes.c_char * 1024),
    ]


# Load the flex-generated shared library
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libddl_lexer.so")
_lib = ctypes.CDLL(_LIB_PATH)

# Set up function prototypes
_lib.ddl_lexer_init.argtypes = [ctypes.c_char_p]
_lib.ddl_lexer_init.restype = None
_lib.ddl_lexer_next.argtypes = [ctypes.POINTER(DDLToken)]
_lib.ddl_lexer_next.restype = ctypes.c_int
_lib.ddl_lexer_free.argtypes = []
_lib.ddl_lexer_free.restype = None

# Mapping from C token type to Python type string
_C_TO_PY = {
    TOK_ID: "ID", TOK_INT: "INT", TOK_STR: "STR",
    TOK_ARROW: "ARROW", TOK_BIASED: "BIASED", TOK_DOTDOT: "DOTDOT",
    TOK_LBPIPE: "LBPIPE", TOK_RBPIPE: "RBPIPE",
    TOK_LE: "LE", TOK_GE: "GE", TOK_EQEQ: "EQEQ",
    TOK_DOLLARDOLLAR: "DOLLARDOLLAR", TOK_DOLLAR: "DOLLAR",
    TOK_LP: "LP", TOK_RP: "RP", TOK_LB: "LB", TOK_RB: "RB",
    TOK_LC: "LC", TOK_RC: "RC",
    TOK_EQ: "EQ", TOK_DOT: "DOT", TOK_COL: "COL", TOK_SEMI: "SEMI",
    TOK_COMMA: "COMMA", TOK_LT: "LT", TOK_GT: "GT",
    TOK_PLUS: "PLUS", TOK_MINUS: "MINUS", TOK_STAR: "STAR",
    TOK_AT: "AT", TOK_CARET: "CARET", TOK_PIPE: "PIPE",
}

# Default display values for non-value tokens
_PY_VALS = {
    "ARROW": "->", "BIASED": "<|", "DOTDOT": "..", "LBPIPE": "{|",
    "RBPIPE": "|}", "LE": "<=", "GE": ">=", "EQEQ": "==",
    "DOLLARDOLLAR": "$$", "DOLLAR": "$",
    "LP": "(", "RP": ")", "LB": "[", "RB": "]", "LC": "{", "RC": "}",
    "EQ": "=", "DOT": ".", "COL": ":", "SEMI": ";", "COMMA": ",",
    "LT": "<", "GT": ">", "PLUS": "+", "MINUS": "-", "STAR": "*",
    "AT": "@", "CARET": "^", "PIPE": "|",
}


def tokenize(src):
    """Tokenize DDL source using the flex-generated shared library."""
    _lib.ddl_lexer_init(src.encode("ascii"))
    tokens = []
    tok = DDLToken()
    while True:
        _lib.ddl_lexer_next(ctypes.byref(tok))
        ctype = tok.type
        if ctype == TOK_EOF:
            tokens.append(Token("EOF", None, tok.line, tok.col))
            break

        py_type = _C_TO_PY.get(ctype)
        if py_type is None:
            continue  # skip unknown token types

        if ctype == TOK_ID:
            val = tok.str_val.decode("ascii")
        elif ctype == TOK_INT:
            val = tok.int_val
        elif ctype == TOK_STR:
            val = tok.str_val.decode("ascii")
        else:
            val = _PY_VALS.get(py_type, "")

        tokens.append(Token(py_type, val, tok.line, tok.col))

    _lib.ddl_lexer_free()
    return tokens


# ============================================================
# Parser
# ============================================================

RESERVED = frozenset({
    "def", "bitdata", "block", "where", "case", "of", "let",
    "as", "is", "true", "false", "import", "uint",
})

BUILTINS = frozenset({"UInt8", "BEUInt16", "BEUInt32", "END"})

KEYWORDS = frozenset({
    "Match", "Many", "First", "Guard", "Fail",
}) | BUILTINS


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def at(self, ty, val=None):
        t = self.peek()
        if t.ty != ty:
            return False
        if val is not None and t.val != val:
            return False
        return True

    def consume(self, ty=None, val=None):
        t = self.toks[self.pos]
        if ty is not None and t.ty != ty:
            raise ParseError(f"Expected {ty}({val}), got {t}")
        if val is not None and t.val != val:
            raise ParseError(f"Expected {ty}({val}), got {t}")
        self.pos += 1
        return t

    def try_consume(self, ty, val=None):
        if self.at(ty, val):
            return self.consume()
        return None

    # ---- top level ----

    def parse_module(self):
        decls = []
        while not self.at("EOF"):
            if self.at("ID", "def"):
                decls.append(self._def())
            elif self.at("ID", "bitdata"):
                decls.append(self._bitdata())
            elif self.at("ID", "import"):
                self.consume()
                self.consume()  # skip module name
            else:
                raise ParseError(f"Unexpected top-level token: {self.peek()}")
        return decls

    def _def(self):
        self.consume("ID", "def")
        name = self.consume("ID").val
        params = []
        if self.at("LP"):
            self.consume()
            pn = self.consume("ID").val
            self.consume("COL")
            pt = self._typespec()
            params.append((pn, pt))
            self.consume("RP")
        self.consume("EQ")
        body = self._expr()
        return {"kind": "def", "name": name, "params": params, "body": body}

    def _typespec(self):
        if self.at("ID", "uint"):
            self.consume()
            w = self.consume("INT").val
            return ("uint", w)
        return ("named", self.consume("ID").val)

    def _bitdata(self):
        self.consume("ID", "bitdata")
        name = self.consume("ID").val
        self.consume("ID", "where")
        ref = self.peek().col
        variants = []
        while (
            not self.at("EOF")
            and self.peek().col == ref
            and not self.at("ID", "def")
            and not self.at("ID", "bitdata")
        ):
            vn = self.consume("ID").val
            if self.at("EQ"):
                self.consume()
                if self.at("LC"):
                    # struct form
                    self.consume("LC")
                    fields = []
                    while not self.at("RC"):
                        fn = self.consume("ID").val
                        self.consume("COL")
                        ft = self._typespec()
                        fields.append((fn, ft))
                        self.try_consume("COMMA")
                    self.consume("RC")
                    variants.append({"name": vn, "form": "struct", "fields": fields})
                else:
                    # enum form: value [: type]
                    v = self.consume("INT").val
                    if self.try_consume("COL"):
                        self._typespec()
                    variants.append({"name": vn, "form": "enum", "value": v})
            else:
                variants.append({"name": vn, "form": "bare"})
        return {"kind": "bitdata", "name": name, "variants": variants}

    # ---- expressions (precedence climbing) ----

    def _expr(self):
        return self._biased()

    def _biased(self):
        left = self._is()
        while self.at("BIASED"):
            self.consume()
            right = self._is()
            left = {"n": "biased", "l": left, "r": right}
        return left

    def _is(self):
        left = self._cmp()
        if self.at("ID", "is"):
            self.consume()
            self.consume("ID", "true")
            return {"n": "is_true", "e": left}
        return left

    def _cmp(self):
        left = self._add()
        for tty, op in [("LE", "<="), ("GE", ">="), ("EQEQ", "=="), ("LT", "<"), ("GT", ">")]:
            if self.at(tty):
                self.consume()
                right = self._add()
                return {"n": "binop", "op": op, "l": left, "r": right}
        return left

    def _add(self):
        left = self._mul()
        while self.at("PLUS") or self.at("MINUS"):
            op = "+" if self.at("PLUS") else "-"
            self.consume()
            right = self._mul()
            left = {"n": "binop", "op": op, "l": left, "r": right}
        return left

    def _mul(self):
        left = self._postfix()
        while self.at("STAR"):
            self.consume()
            right = self._postfix()
            left = {"n": "binop", "op": "*", "l": left, "r": right}
        return left

    def _postfix(self):
        left = self._app()
        while True:
            if self.at("DOT"):
                self.consume()
                f = self.consume("ID").val
                left = {"n": "field", "e": left, "f": f}
            elif self.at("ID", "as?") or self.at("ID", "as!"):
                m = self.consume().val
                t = self._typespec()
                left = {"n": "coerce", "mode": m, "e": left, "t": t}
            elif self.at("ID", "as"):
                self.consume()
                t = self._typespec()
                left = {"n": "coerce", "mode": "as", "e": left, "t": t}
            else:
                break
        return left

    def _app(self):
        atom = self._atom()
        # check for user-defined parser application
        if (
            atom.get("n") == "var"
            and atom["v"][0].isupper()
            and atom["v"] not in KEYWORDS
        ):
            cur = self.peek()
            on_same_line = cur.line == atom.get("_line", -1)
            is_arg = (
                (cur.ty == "ID" and cur.val[0].islower() and cur.val not in RESERVED)
                or cur.ty == "INT"
                or cur.ty == "LP"
            )
            if on_same_line and is_arg:
                arg = self._postfix()
                return {"n": "call", "name": atom["v"], "args": [arg]}
        return atom

    def _atom(self):
        t = self.peek()

        if t.ty == "ID" and t.val == "block":
            return self._block()
        if t.ty == "ID" and t.val == "First":
            return self._first()
        if t.ty == "ID" and t.val == "case":
            return self._case()
        if t.ty == "ID" and t.val == "Match":
            self.consume()
            self.consume("LB")
            bs = []
            while not self.at("RB"):
                bs.append(self.consume("INT").val)
                self.try_consume("COMMA")
                self.try_consume("SEMI")
            self.consume("RB")
            return {"n": "match", "bytes": bs}
        if t.ty == "ID" and t.val == "Many":
            return self._many()
        if t.ty == "ID" and t.val == "Guard":
            self.consume()
            self.consume("LP")
            c = self._expr()
            self.consume("RP")
            return {"n": "guard", "c": c}
        if t.ty == "ID" and t.val == "Fail":
            self.consume()
            msg = self.consume("STR").val
            return {"n": "fail", "msg": msg}
        if t.ty == "ID" and t.val in BUILTINS:
            self.consume()
            return {"n": "builtin", "name": t.val}
        if t.ty == "INT":
            self.consume()
            return {"n": "int", "v": t.val}
        if t.ty == "STR":
            self.consume()
            return {"n": "str", "v": t.val}
        if t.ty == "DOLLAR":
            return self._charclass()
        if t.ty == "LBPIPE":
            return self._tagged()
        if t.ty == "LP":
            self.consume()
            e = self._expr()
            self.consume("RP")
            return e
        if t.ty == "CARET":
            self.consume()
            v = self._atom()
            return {"n": "pure", "v": v}
        if t.ty == "AT":
            self.consume()
            e = self._atom()
            return {"n": "suppress", "e": e}
        if t.ty == "ID" and t.val == "true":
            self.consume()
            return {"n": "bool", "v": True}
        if t.ty == "ID" and t.val == "false":
            self.consume()
            return {"n": "bool", "v": False}
        if t.ty == "ID":
            self.consume()
            return {"n": "var", "v": t.val, "_line": t.line}

        raise ParseError(f"Unexpected token in expression: {t}")

    # ---- compound constructs ----

    def _block(self):
        self.consume("ID", "block")
        ref = self.peek().col
        items = []
        while not self.at("EOF") and self.peek().col == ref:
            items.append(self._block_item())
        return {"n": "block", "items": items}

    def _block_item(self):
        t = self.peek()
        t2 = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else None

        # $$ = expr
        if t.ty == "DOLLARDOLLAR":
            self.consume()
            self.consume("EQ")
            e = self._expr()
            return {"it": "result", "e": e}

        # let name = expr
        if t.ty == "ID" and t.val == "let":
            self.consume()
            nm = self.consume("ID").val
            self.consume("EQ")
            e = self._expr()
            return {"it": "let", "name": nm, "e": e}

        # name = expr (field)
        if (
            t.ty == "ID"
            and t2 is not None
            and t2.ty == "EQ"
            and t.val[0].islower()
            and t.val not in RESERVED
        ):
            nm = self.consume("ID").val
            self.consume("EQ")
            e = self._expr()
            return {"it": "field", "name": nm, "e": e}

        # statement
        e = self._expr()
        return {"it": "stmt", "e": e}

    def _first(self):
        self.consume("ID", "First")
        ref = self.peek().col
        alts = []
        while (
            not self.at("EOF")
            and self.peek().col == ref
            and self.peek().ty == "ID"
            and self.peek().val not in {"def", "bitdata"}
        ):
            nm = self.consume("ID").val
            self.consume("EQ")
            e = self._expr()
            alts.append((nm, e))
        return {"n": "first", "alts": alts}

    def _case(self):
        self.consume("ID", "case")
        scr = self._expr()
        self.consume("ID", "of")
        ref = self.peek().col
        arms = []
        while not self.at("EOF") and self.peek().col == ref:
            if self.at("ID", "_"):
                self.consume()
                pat = ("wild",)
            elif self.at("INT"):
                pat = ("int", self.consume("INT").val)
            elif self.at("ID"):
                pat = ("name", self.consume("ID").val)
            else:
                break
            self.consume("ARROW")
            e = self._expr()
            arms.append((pat, e))
        return {"n": "case", "scr": scr, "arms": arms}

    def _many(self):
        self.consume("ID", "Many")
        t = self.peek()
        is_count = False
        if t.ty == "LP":
            is_count = True
        elif t.ty == "ID" and t.val[0].islower() and t.val not in RESERVED:
            is_count = True
        elif t.ty == "INT":
            is_count = True

        if is_count:
            count = self._postfix()
            body = self._postfix()
            return {"n": "many", "count": count, "body": body}
        else:
            body = self._postfix()
            return {"n": "many", "count": None, "body": body}

    def _charclass(self):
        self.consume("DOLLAR")
        self.consume("LB")
        ranges = []
        while not self.at("RB"):
            lo = self.consume("INT").val
            if self.at("DOTDOT"):
                self.consume()
                hi = self.consume("INT").val
                ranges.append((lo, hi))
            else:
                ranges.append((lo, lo))
            self.try_consume("COMMA")
        self.consume("RB")
        return {"n": "cc", "ranges": ranges}

    def _tagged(self):
        self.consume("LBPIPE")
        tag = self.consume("ID").val
        if self.at("EQ"):
            self.consume()
            val = self._expr()
        else:
            val = {"n": "unit"}
        self.consume("RBPIPE")
        return {"n": "tagged", "tag": tag, "val": val}


# ============================================================
# Interpreter
# ============================================================

class InterpError(Exception):
    pass


class Stream:
    __slots__ = ("data", "pos")

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n=1):
        if self.pos + n > len(self.data):
            raise InterpError(
                f"Unexpected end of input at pos {self.pos} (need {n} bytes)"
            )
        r = self.data[self.pos : self.pos + n]
        self.pos += n
        return r

    def at_end(self):
        return self.pos >= len(self.data)

    def save(self):
        return self.pos

    def restore(self, p):
        self.pos = p


class Interp:
    def __init__(self, decls, stream):
        self.defs = {}
        self.bds = {}
        self.stream = stream
        for d in decls:
            if d["kind"] == "def":
                self.defs[d["name"]] = d
            elif d["kind"] == "bitdata":
                self.bds[d["name"]] = d

    def run(self):
        return self._call("Main", [])

    def _call(self, name, args):
        d = self.defs.get(name)
        if d is None:
            raise InterpError(f"Undefined parser: {name}")
        env = {}
        for (pn, _), av in zip(d["params"], args):
            env[pn] = av
        return self._eval(d["body"], env)

    def _eval(self, e, env):
        n = e.get("n")

        if n == "block":
            return self._eval_block(e, env)
        if n == "first":
            return self._eval_first(e, env)
        if n == "case":
            return self._eval_case(e, env)

        if n == "match":
            exp = bytes(e["bytes"])
            got = self.stream.read(len(exp))
            if got != exp:
                raise InterpError(f"Match failed: expected {exp.hex()}, got {got.hex()}")
            return None

        if n == "many":
            return self._eval_many(e, env)

        if n == "guard":
            if not self._pure(e["c"], env):
                raise InterpError("Guard failed")
            return None

        if n == "fail":
            raise InterpError(f"Fail: {e['msg']}")

        if n == "builtin":
            nm = e["name"]
            if nm == "UInt8":
                return self.stream.read(1)[0]
            if nm == "BEUInt16":
                return struct.unpack(">H", self.stream.read(2))[0]
            if nm == "BEUInt32":
                return struct.unpack(">I", self.stream.read(4))[0]
            if nm == "END":
                if not self.stream.at_end():
                    raise InterpError(
                        f"Expected end, {len(self.stream.data) - self.stream.pos} bytes remain"
                    )
                return None

        if n == "int":
            return e["v"]
        if n == "str":
            return e["v"]
        if n == "bool":
            return e["v"]

        if n == "var":
            nm = e["v"]
            if nm in env:
                return env[nm]
            if nm in self.defs:
                return self._call(nm, [])
            raise InterpError(f"Undefined: {nm}")

        if n == "call":
            args = [self._pure(a, env) for a in e["args"]]
            return self._call(e["name"], args)

        if n == "coerce":
            val = self._eval(e["e"], env)
            return self._coerce(val, e["mode"], e["t"])

        if n == "field":
            obj = self._pure(e["e"], env)
            return obj[e["f"]]

        if n == "cc":
            b = self.stream.read(1)[0]
            for lo, hi in e["ranges"]:
                if lo <= b <= hi:
                    return b
            raise InterpError(f"Byte {b:#x} not in character class")

        if n == "tagged":
            val = self._eval(e["val"], env)
            return {e["tag"]: val}

        if n == "biased":
            sv = self.stream.save()
            try:
                return self._eval(e["l"], env)
            except InterpError:
                self.stream.restore(sv)
                return self._eval(e["r"], env)

        if n == "is_true":
            val = self._pure(e["e"], env)
            if not val:
                raise InterpError("is true assertion failed")
            return None

        if n == "binop":
            return self._binop(e["op"], self._pure(e["l"], env), self._pure(e["r"], env))

        if n == "pure":
            return self._pure(e["v"], env)

        if n == "suppress":
            self._eval(e["e"], env)
            return None

        if n == "unit":
            return None

        raise InterpError(f"Unknown node type: {n}")

    def _pure(self, e, env):
        """Evaluate a pure (non-parsing) expression."""
        n = e.get("n")
        if n == "int":
            return e["v"]
        if n == "str":
            return e["v"]
        if n == "bool":
            return e["v"]
        if n == "var":
            if e["v"] in env:
                return env[e["v"]]
            raise InterpError(f"Undefined variable: {e['v']}")
        if n == "field":
            obj = self._pure(e["e"], env)
            return obj[e["f"]]
        if n == "coerce":
            val = self._pure(e["e"], env)
            return self._coerce(val, e["mode"], e["t"])
        if n == "binop":
            return self._binop(e["op"], self._pure(e["l"], env), self._pure(e["r"], env))
        # fallback: run as parser
        return self._eval(e, env)

    def _binop(self, op, a, b):
        ops = {
            "<=": lambda x, y: x <= y,
            ">=": lambda x, y: x >= y,
            "==": lambda x, y: x == y,
            "<": lambda x, y: x < y,
            ">": lambda x, y: x > y,
            "+": lambda x, y: x + y,
            "-": lambda x, y: x - y,
            "*": lambda x, y: x * y,
        }
        return ops[op](a, b)

    def _coerce(self, val, mode, target):
        if mode == "as" and target[0] == "uint":
            return int(val)
        if mode in ("as?", "as!") and target[0] == "named":
            bd = self.bds.get(target[1])
            if bd is None:
                raise InterpError(f"Unknown bitdata: {target[1]}")
            if bd["variants"][0]["form"] == "enum":
                for v in bd["variants"]:
                    if v["value"] == val:
                        return v["name"]
                raise InterpError(
                    f"Value {val} doesn't match any variant of {target[1]}"
                )
            elif bd["variants"][0]["form"] == "struct":
                fields = bd["variants"][0]["fields"]
                result = {}
                total = sum(f[1][1] for f in fields)
                remaining = total
                for fn, (_, width) in fields:
                    remaining -= width
                    result[fn] = (int(val) >> remaining) & ((1 << width) - 1)
                return result
        if mode == "as" and target[0] == "named":
            return val
        raise InterpError(f"Unsupported coercion: {mode} {target}")

    def _eval_block(self, e, env):
        local = dict(env)
        fields = {}
        explicit_result = None
        has_result = False
        last_val = None

        for item in e["items"]:
            it = item["it"]
            if it == "field":
                v = self._eval(item["e"], local)
                fields[item["name"]] = v
                local[item["name"]] = v
            elif it == "let":
                v = self._eval(item["e"], local)
                local[item["name"]] = v
            elif it == "result":
                explicit_result = self._eval(item["e"], local)
                has_result = True
            elif it == "stmt":
                last_val = self._eval(item["e"], local)

        if has_result:
            return explicit_result
        if fields:
            return fields
        return last_val

    def _eval_first(self, e, env):
        last = None
        for name, alt in e["alts"]:
            sv = self.stream.save()
            try:
                val = self._eval(alt, env)
                return {name: val}
            except InterpError as ex:
                self.stream.restore(sv)
                last = ex
        raise InterpError(f"All First alternatives failed: {last}")

    def _eval_case(self, e, env):
        scr = self._pure(e["scr"], env)
        for pat, arm in e["arms"]:
            if pat[0] == "wild":
                return self._eval(arm, env)
            if pat[0] == "int" and scr == pat[1]:
                return self._eval(arm, env)
            if pat[0] == "name" and scr == pat[1]:
                return self._eval(arm, env)
        raise InterpError(f"No case arm matched value {scr}")

    def _eval_many(self, e, env):
        if e["count"] is not None:
            cnt = int(self._pure(e["count"], env))
            return [self._eval(e["body"], env) for _ in range(cnt)]
        else:
            results = []
            while True:
                sv = self.stream.save()
                try:
                    results.append(self._eval(e["body"], env))
                except InterpError:
                    self.stream.restore(sv)
                    break
            return results


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <spec.ddl> <input.bin>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        src = f.read()
    with open(sys.argv[2], "rb") as f:
        data = f.read()

    try:
        toks = tokenize(src)
        p = Parser(toks)
        decls = p.parse_module()
        interp = Interp(decls, Stream(data))
        result = interp.run()
        print(json.dumps(result, indent=2))
    except (ParseError, InterpError) as ex:
        print(f"Error: {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
