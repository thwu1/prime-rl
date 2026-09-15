#!/usr/bin/env python3
"""Cool language evaluator — reads token stream from stdin, parses and executes."""

import sys

# ============================================================
# Token reader (reads from Flex tokenizer stdout via stdin)
# ============================================================

_OP_MAP = {
    'PLUS': '+', 'MINUS': '-', 'TIMES': '*', 'DIVIDE': '/',
    'LT': '<', 'EQ': '=', 'TILDE': '~', 'AT': '@', 'DOT': '.',
    'LPAREN': '(', 'RPAREN': ')', 'LBRACE': '{', 'RBRACE': '}',
    'SEMI': ';', 'COLON': ':', 'COMMA': ',',
}

_MULTI_OP_MAP = {
    'DARROW': ('=>',), 'LE': ('<=',), 'ASSIGN': ('<-',),
}

_KEYWORDS = frozenset([
    'CLASS', 'ELSE', 'FI', 'IF', 'IN', 'INHERITS', 'ISVOID',
    'LET', 'LOOP', 'POOL', 'NEW', 'OF', 'NOT', 'THEN',
    'WHILE', 'CASE', 'ESAC',
])


class Token:
    __slots__ = ('type', 'value', 'line')

    def __init__(self, typ, value, line):
        self.type = typ
        self.value = value
        self.line = line

    def __repr__(self):
        return f'Token({self.type!r}, {self.value!r}, {self.line})'


def _decode_str(s):
    """Decode escape sequences from tokenizer string output."""
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            if c == 'n':
                result.append('\n')
            elif c == 't':
                result.append('\t')
            elif c == 'b':
                result.append('\b')
            elif c == 'f':
                result.append('\f')
            elif c == '\\':
                result.append('\\')
            elif c == 'r':
                result.append('\r')
            else:
                result.append(c)
            i += 2
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def read_tokens():
    """Read token stream from stdin (piped from tokenizer)."""
    tokens = []
    line_num = 1
    for raw in sys.stdin:
        raw = raw.rstrip('\n\r')
        if not raw:
            continue
        parts = raw.split(' ', 1)
        ttype = parts[0]
        tvalue = parts[1] if len(parts) > 1 else None

        if ttype == 'EOF':
            break
        elif ttype == 'INT_CONST':
            tokens.append(Token('INT', int(tvalue), line_num))
        elif ttype == 'STR_CONST':
            tokens.append(Token('STRING', _decode_str(tvalue if tvalue else ''), line_num))
        elif ttype == 'BOOL_CONST':
            tokens.append(Token('BOOL', tvalue == 'true', line_num))
        elif ttype == 'TYPEID':
            tokens.append(Token('TYPEID', tvalue, line_num))
        elif ttype == 'OBJECTID':
            tokens.append(Token('OBJECTID', tvalue, line_num))
        elif ttype in _KEYWORDS:
            tokens.append(Token(ttype, ttype.lower(), line_num))
        elif ttype in _MULTI_OP_MAP:
            val = _MULTI_OP_MAP[ttype][0]
            tokens.append(Token(ttype, val, line_num))
        elif ttype in _OP_MAP:
            op = _OP_MAP[ttype]
            tokens.append(Token(op, op, line_num))
        else:
            _err(f"Unknown token type from tokenizer: {ttype}")
        line_num += 1

    tokens.append(Token('EOF', None, line_num))
    return tokens


def _err(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


# ============================================================
# AST Nodes
# ============================================================

class Program:
    __slots__ = ('classes',)
    def __init__(self, classes):
        self.classes = classes

class ClassDef:
    __slots__ = ('name', 'parent', 'features', 'line')
    def __init__(self, name, parent, features, line):
        self.name = name; self.parent = parent
        self.features = features; self.line = line

class MethodDef:
    __slots__ = ('name', 'formals', 'ret_type', 'body', 'line')
    def __init__(self, name, formals, ret_type, body, line):
        self.name = name; self.formals = formals
        self.ret_type = ret_type; self.body = body; self.line = line

class AttrDef:
    __slots__ = ('name', 'type_name', 'init', 'line')
    def __init__(self, name, type_name, init, line):
        self.name = name; self.type_name = type_name
        self.init = init; self.line = line

class Formal:
    __slots__ = ('name', 'type_name')
    def __init__(self, name, type_name):
        self.name = name; self.type_name = type_name

class IntConst:
    __slots__ = ('value', 'line')
    def __init__(self, v, l): self.value = v; self.line = l

class StringConst:
    __slots__ = ('value', 'line')
    def __init__(self, v, l): self.value = v; self.line = l

class BoolConst:
    __slots__ = ('value', 'line')
    def __init__(self, v, l): self.value = v; self.line = l

class Identifier:
    __slots__ = ('name', 'line')
    def __init__(self, n, l): self.name = n; self.line = l

class Assign:
    __slots__ = ('name', 'value', 'line')
    def __init__(self, n, v, l): self.name = n; self.value = v; self.line = l

class Dispatch:
    __slots__ = ('obj', 'method', 'args', 'line')
    def __init__(self, o, m, a, l): self.obj = o; self.method = m; self.args = a; self.line = l

class StaticDispatch:
    __slots__ = ('obj', 'type_name', 'method', 'args', 'line')
    def __init__(self, o, t, m, a, l):
        self.obj = o; self.type_name = t; self.method = m
        self.args = a; self.line = l

class SelfDispatch:
    __slots__ = ('method', 'args', 'line')
    def __init__(self, m, a, l): self.method = m; self.args = a; self.line = l

class If:
    __slots__ = ('pred', 'then_expr', 'else_expr', 'line')
    def __init__(self, p, t, e, l):
        self.pred = p; self.then_expr = t; self.else_expr = e; self.line = l

class While:
    __slots__ = ('pred', 'body', 'line')
    def __init__(self, p, b, l): self.pred = p; self.body = b; self.line = l

class Block:
    __slots__ = ('exprs', 'line')
    def __init__(self, e, l): self.exprs = e; self.line = l

class Let:
    __slots__ = ('name', 'type_name', 'init', 'body', 'line')
    def __init__(self, n, t, i, b, l):
        self.name = n; self.type_name = t; self.init = i
        self.body = b; self.line = l

class Case:
    __slots__ = ('expr', 'branches', 'line')
    def __init__(self, e, b, l): self.expr = e; self.branches = b; self.line = l

class CaseBranch:
    __slots__ = ('name', 'type_name', 'body', 'line')
    def __init__(self, n, t, b, l):
        self.name = n; self.type_name = t; self.body = b; self.line = l

class New:
    __slots__ = ('type_name', 'line')
    def __init__(self, t, l): self.type_name = t; self.line = l

class IsVoid:
    __slots__ = ('expr', 'line')
    def __init__(self, e, l): self.expr = e; self.line = l

class Arith:
    __slots__ = ('op', 'left', 'right', 'line')
    def __init__(self, o, le, r, l):
        self.op = o; self.left = le; self.right = r; self.line = l

class Comp:
    __slots__ = ('op', 'left', 'right', 'line')
    def __init__(self, o, le, r, l):
        self.op = o; self.left = le; self.right = r; self.line = l

class Not:
    __slots__ = ('expr', 'line')
    def __init__(self, e, l): self.expr = e; self.line = l

class Negate:
    __slots__ = ('expr', 'line')
    def __init__(self, e, l): self.expr = e; self.line = l


# ============================================================
# Parser
# ============================================================

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def cur(self):
        return self.tokens[self.pos]

    def eat(self, typ):
        t = self.cur()
        if t.type != typ:
            _err(f"Line {t.line}: Expected {typ}, got {t.type} ({t.value!r})")
        self.pos += 1
        return t

    def parse(self):
        classes = []
        while self.cur().type != 'EOF':
            classes.append(self._class())
        return Program(classes)

    def _class(self):
        t = self.eat('CLASS')
        name = self.eat('TYPEID').value
        parent = 'Object'
        if self.cur().type == 'INHERITS':
            self.eat('INHERITS')
            parent = self.eat('TYPEID').value
        self.eat('{')
        features = []
        while self.cur().type != '}':
            features.append(self._feature())
            self.eat(';')
        self.eat('}')
        self.eat(';')
        return ClassDef(name, parent, features, t.line)

    def _feature(self):
        t = self.eat('OBJECTID')
        name = t.value
        if self.cur().type == '(':
            self.eat('(')
            formals = self._formals()
            self.eat(')')
            self.eat(':')
            ret = self.eat('TYPEID').value
            self.eat('{')
            body = self._expr()
            self.eat('}')
            return MethodDef(name, formals, ret, body, t.line)
        else:
            self.eat(':')
            typ = self.eat('TYPEID').value
            init = None
            if self.cur().type == 'ASSIGN':
                self.eat('ASSIGN')
                init = self._expr()
            return AttrDef(name, typ, init, t.line)

    def _formals(self):
        formals = []
        if self.cur().type == 'OBJECTID':
            formals.append(self._formal())
            while self.cur().type == ',':
                self.eat(',')
                formals.append(self._formal())
        return formals

    def _formal(self):
        name = self.eat('OBJECTID').value
        self.eat(':')
        typ = self.eat('TYPEID').value
        return Formal(name, typ)

    def _args(self):
        args = []
        if self.cur().type != ')':
            args.append(self._expr())
            while self.cur().type == ',':
                self.eat(',')
                args.append(self._expr())
        return args

    def _expr(self):
        return self._assign()

    def _assign(self):
        if (self.cur().type == 'OBJECTID' and
                self.pos + 1 < len(self.tokens) and
                self.tokens[self.pos + 1].type == 'ASSIGN'):
            t = self.eat('OBJECTID')
            self.eat('ASSIGN')
            val = self._assign()
            return Assign(t.value, val, t.line)
        return self._not()

    def _not(self):
        if self.cur().type == 'NOT':
            t = self.eat('NOT')
            e = self._not()
            return Not(e, t.line)
        return self._comp()

    def _comp(self):
        left = self._add()
        if self.cur().type in ('LE', '<', '='):
            t = self.cur()
            self.pos += 1
            right = self._add()
            return Comp(t.type, left, right, t.line)
        return left

    def _add(self):
        left = self._mul()
        while self.cur().type in ('+', '-'):
            t = self.cur()
            self.pos += 1
            right = self._mul()
            left = Arith(t.type, left, right, t.line)
        return left

    def _mul(self):
        left = self._isvoid()
        while self.cur().type in ('*', '/'):
            t = self.cur()
            self.pos += 1
            right = self._isvoid()
            left = Arith(t.type, left, right, t.line)
        return left

    def _isvoid(self):
        if self.cur().type == 'ISVOID':
            t = self.eat('ISVOID')
            e = self._isvoid()
            return IsVoid(e, t.line)
        return self._negate()

    def _negate(self):
        if self.cur().type == '~':
            t = self.eat('~')
            e = self._negate()
            return Negate(e, t.line)
        return self._dispatch()

    def _dispatch(self):
        expr = self._primary()
        while self.cur().type in ('.', '@'):
            if self.cur().type == '@':
                self.eat('@')
                typ = self.eat('TYPEID').value
                self.eat('.')
                method = self.eat('OBJECTID').value
                self.eat('(')
                args = self._args()
                self.eat(')')
                expr = StaticDispatch(expr, typ, method, args, expr.line)
            else:
                self.eat('.')
                method = self.eat('OBJECTID').value
                self.eat('(')
                args = self._args()
                self.eat(')')
                expr = Dispatch(expr, method, args, expr.line)
        return expr

    def _primary(self):
        t = self.cur()

        if t.type == 'INT':
            self.pos += 1
            return IntConst(t.value, t.line)

        if t.type == 'STRING':
            self.pos += 1
            return StringConst(t.value, t.line)

        if t.type == 'BOOL':
            self.pos += 1
            return BoolConst(t.value, t.line)

        if t.type == 'OBJECTID':
            self.pos += 1
            if self.cur().type == '(':
                self.eat('(')
                args = self._args()
                self.eat(')')
                return SelfDispatch(t.value, args, t.line)
            return Identifier(t.value, t.line)

        if t.type == '(':
            self.eat('(')
            e = self._expr()
            self.eat(')')
            return e

        if t.type == 'IF':
            return self._if()

        if t.type == 'WHILE':
            return self._while()

        if t.type == '{':
            return self._block()

        if t.type == 'LET':
            return self._let()

        if t.type == 'CASE':
            return self._case()

        if t.type == 'NEW':
            self.eat('NEW')
            typ = self.eat('TYPEID')
            return New(typ.value, t.line)

        _err(f"Line {t.line}: Unexpected token {t.type} ({t.value!r})")

    def _if(self):
        t = self.eat('IF')
        pred = self._expr()
        self.eat('THEN')
        then_e = self._expr()
        self.eat('ELSE')
        else_e = self._expr()
        self.eat('FI')
        return If(pred, then_e, else_e, t.line)

    def _while(self):
        t = self.eat('WHILE')
        pred = self._expr()
        self.eat('LOOP')
        body = self._expr()
        self.eat('POOL')
        return While(pred, body, t.line)

    def _block(self):
        t = self.eat('{')
        exprs = []
        exprs.append(self._expr())
        self.eat(';')
        while self.cur().type != '}':
            exprs.append(self._expr())
            self.eat(';')
        self.eat('}')
        return Block(exprs, t.line)

    def _let(self):
        self.eat('LET')
        return self._let_bindings()

    def _let_bindings(self):
        t = self.eat('OBJECTID')
        name = t.value
        self.eat(':')
        typ = self.eat('TYPEID').value
        init = None
        if self.cur().type == 'ASSIGN':
            self.eat('ASSIGN')
            init = self._expr()
        if self.cur().type == ',':
            self.eat(',')
            body = self._let_bindings()
        else:
            self.eat('IN')
            body = self._expr()
        return Let(name, typ, init, body, t.line)

    def _case(self):
        t = self.eat('CASE')
        expr = self._expr()
        self.eat('OF')
        branches = []
        while self.cur().type != 'ESAC':
            bt = self.eat('OBJECTID')
            bname = bt.value
            self.eat(':')
            btype = self.eat('TYPEID').value
            self.eat('DARROW')
            bbody = self._expr()
            self.eat(';')
            branches.append(CaseBranch(bname, btype, bbody, bt.line))
        self.eat('ESAC')
        return Case(expr, branches, t.line)


# ============================================================
# Runtime
# ============================================================

_NOT_FOUND = object()


class CoolVoid:
    """Represents the void value."""
    pass


VOID = CoolVoid()


class CoolObject:
    __slots__ = ('class_name', 'attrs')

    def __init__(self, class_name):
        self.class_name = class_name
        self.attrs = {}


class Environment:
    __slots__ = ('bindings', 'parent')

    def __init__(self, parent=None):
        self.bindings = {}
        self.parent = parent

    def lookup(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return _NOT_FOUND

    def set(self, name, value):
        if name in self.bindings:
            self.bindings[name] = value
            return True
        if self.parent is not None:
            return self.parent.set(name, value)
        return False

    def define(self, name, value):
        self.bindings[name] = value

    def child(self):
        return Environment(parent=self)


# ============================================================
# Interpreter
# ============================================================

class Interpreter:
    def __init__(self, program, filename):
        self.filename = filename
        self.classes = {}
        self.methods = {}
        self.class_attrs = {}
        self.parents = {}

        self.parents['Object'] = None
        self.parents['IO'] = 'Object'
        self.parents['Int'] = 'Object'
        self.parents['String'] = 'Object'
        self.parents['Bool'] = 'Object'
        self.class_attrs['Object'] = []
        self.class_attrs['IO'] = []
        self.class_attrs['Int'] = []
        self.class_attrs['String'] = []
        self.class_attrs['Bool'] = []

        for cls in program.classes:
            self.classes[cls.name] = cls
            self.parents[cls.name] = cls.parent
            attrs = []
            for f in cls.features:
                if isinstance(f, MethodDef):
                    self.methods[(cls.name, f.name)] = f
                elif isinstance(f, AttrDef):
                    attrs.append(f)
            self.class_attrs[cls.name] = attrs

    def run(self):
        main_obj = self._new_object('Main')
        self._call_method(main_obj, main_obj.class_name, 'main', [])

    def _new_object(self, class_name):
        obj = CoolObject(class_name)
        chain = self._inheritance_chain(class_name)
        for cname in chain:
            for attr in self.class_attrs.get(cname, []):
                if attr.init is not None:
                    val = self._eval(attr.init, obj, Environment())
                else:
                    val = self._default(attr.type_name)
                obj.attrs[attr.name] = val
        return obj

    def _inheritance_chain(self, class_name):
        chain = []
        c = class_name
        while c is not None:
            chain.append(c)
            c = self.parents.get(c)
        chain.reverse()
        return chain

    def _conforms(self, child, ancestor):
        c = child
        while c is not None:
            if c == ancestor:
                return True
            c = self.parents.get(c)
        return False

    def _type_distance(self, from_type, to_type):
        d = 0
        c = from_type
        while c is not None:
            if c == to_type:
                return d
            c = self.parents.get(c)
            d += 1
        return None

    def _default(self, type_name):
        if type_name == 'Int':
            return self._make_int(0)
        if type_name == 'String':
            return self._make_string('')
        if type_name == 'Bool':
            return self._make_bool(False)
        return VOID

    def _make_int(self, v):
        obj = CoolObject('Int')
        obj.attrs['val'] = v
        return obj

    def _make_string(self, v):
        obj = CoolObject('String')
        obj.attrs['val'] = v
        return obj

    def _make_bool(self, v):
        obj = CoolObject('Bool')
        obj.attrs['val'] = v
        return obj

    def _call_method(self, obj, start_class, method_name, args):
        c = start_class
        while c is not None:
            key = (c, method_name)
            if key in self.methods:
                meth = self.methods[key]
                env = Environment()
                for i, formal in enumerate(meth.formals):
                    env.define(formal.name, args[i])
                return self._eval(meth.body, obj, env)
            c = self.parents.get(c)
        return self._call_builtin(obj, method_name, args)

    def _call_builtin(self, obj, method_name, args):
        if method_name == 'abort':
            print(f"Abort called from class {obj.class_name}", file=sys.stderr)
            sys.exit(1)
        if method_name == 'type_name':
            return self._make_string(obj.class_name)
        if method_name == 'copy':
            new = CoolObject(obj.class_name)
            new.attrs = dict(obj.attrs)
            return new

        if self._conforms(obj.class_name, 'IO'):
            if method_name == 'out_string':
                sys.stdout.write(args[0].attrs['val'])
                return obj
            if method_name == 'out_int':
                sys.stdout.write(str(args[0].attrs['val']))
                return obj
            if method_name == 'in_string':
                try:
                    s = input()
                except EOFError:
                    s = ''
                return self._make_string(s)
            if method_name == 'in_int':
                try:
                    s = input()
                    n = int(s.strip())
                except (EOFError, ValueError):
                    n = 0
                return self._make_int(n)

        if obj.class_name == 'String':
            if method_name == 'length':
                return self._make_int(len(obj.attrs['val']))
            if method_name == 'concat':
                return self._make_string(obj.attrs['val'] + args[0].attrs['val'])
            if method_name == 'substr':
                s = obj.attrs['val']
                idx = args[0].attrs['val']
                length = args[1].attrs['val']
                if idx < 0 or length < 0 or idx + length > len(s):
                    self._runtime_error(0, "Substring out of range")
                return self._make_string(s[idx:idx + length])

        self._runtime_error(0, f"No method {method_name} in class {obj.class_name}")

    def _runtime_error(self, line, msg):
        print(f"ERROR: {self.filename}:{line}: {msg}", file=sys.stderr)
        sys.exit(1)

    def _eval(self, expr, self_obj, env):
        if isinstance(expr, IntConst):
            return self._make_int(expr.value)

        if isinstance(expr, StringConst):
            return self._make_string(expr.value)

        if isinstance(expr, BoolConst):
            return self._make_bool(expr.value)

        if isinstance(expr, Identifier):
            if expr.name == 'self':
                return self_obj
            v = env.lookup(expr.name)
            if v is not _NOT_FOUND:
                return v
            if expr.name in self_obj.attrs:
                return self_obj.attrs[expr.name]
            self._runtime_error(expr.line, f"Undefined variable '{expr.name}'")

        if isinstance(expr, Assign):
            val = self._eval(expr.value, self_obj, env)
            if not env.set(expr.name, val):
                if expr.name in self_obj.attrs:
                    self_obj.attrs[expr.name] = val
                else:
                    self._runtime_error(expr.line, f"Undefined variable '{expr.name}'")
            return val

        if isinstance(expr, Dispatch):
            obj = self._eval(expr.obj, self_obj, env)
            if isinstance(obj, CoolVoid):
                self._runtime_error(expr.line, "Dispatch to void")
            eargs = [self._eval(a, self_obj, env) for a in expr.args]
            return self._call_method(obj, obj.class_name, expr.method, eargs)

        if isinstance(expr, StaticDispatch):
            obj = self._eval(expr.obj, self_obj, env)
            if isinstance(obj, CoolVoid):
                self._runtime_error(expr.line, "Dispatch to void")
            eargs = [self._eval(a, self_obj, env) for a in expr.args]
            return self._call_method(obj, expr.type_name, expr.method, eargs)

        if isinstance(expr, SelfDispatch):
            eargs = [self._eval(a, self_obj, env) for a in expr.args]
            return self._call_method(self_obj, self_obj.class_name, expr.method, eargs)

        if isinstance(expr, If):
            cond = self._eval(expr.pred, self_obj, env)
            if cond.attrs['val']:
                return self._eval(expr.then_expr, self_obj, env)
            else:
                return self._eval(expr.else_expr, self_obj, env)

        if isinstance(expr, While):
            while True:
                cond = self._eval(expr.pred, self_obj, env)
                if not cond.attrs['val']:
                    break
                self._eval(expr.body, self_obj, env)
            return VOID

        if isinstance(expr, Block):
            result = VOID
            for e in expr.exprs:
                result = self._eval(e, self_obj, env)
            return result

        if isinstance(expr, Let):
            new_env = env.child()
            if expr.init is not None:
                val = self._eval(expr.init, self_obj, env)
            else:
                val = self._default(expr.type_name)
            new_env.define(expr.name, val)
            return self._eval(expr.body, self_obj, new_env)

        if isinstance(expr, Case):
            val = self._eval(expr.expr, self_obj, env)
            if isinstance(val, CoolVoid):
                self._runtime_error(expr.line, "Case on void")
            dyn_type = val.class_name
            best = None
            best_dist = None
            for branch in expr.branches:
                d = self._type_distance(dyn_type, branch.type_name)
                if d is not None and (best_dist is None or d < best_dist):
                    best_dist = d
                    best = branch
            if best is None:
                self._runtime_error(expr.line, "No matching branch in case")
            new_env = env.child()
            new_env.define(best.name, val)
            return self._eval(best.body, self_obj, new_env)

        if isinstance(expr, New):
            typ = expr.type_name
            if typ == 'SELF_TYPE':
                typ = self_obj.class_name
            return self._new_object(typ)

        if isinstance(expr, IsVoid):
            val = self._eval(expr.expr, self_obj, env)
            return self._make_bool(isinstance(val, CoolVoid))

        if isinstance(expr, Arith):
            left = self._eval(expr.left, self_obj, env)
            right = self._eval(expr.right, self_obj, env)
            lv = left.attrs['val']
            rv = right.attrs['val']
            op = expr.op
            if op == '+':
                return self._make_int(lv + rv)
            if op == '-':
                return self._make_int(lv - rv)
            if op == '*':
                return self._make_int(lv * rv)
            if op == '/':
                if rv == 0:
                    self._runtime_error(expr.line, "Division by zero")
                r = abs(lv) // abs(rv)
                if (lv < 0) != (rv < 0) and r != 0:
                    r = -r
                return self._make_int(r)

        if isinstance(expr, Comp):
            left = self._eval(expr.left, self_obj, env)
            right = self._eval(expr.right, self_obj, env)
            op = expr.op
            if op == '<':
                return self._make_bool(left.attrs['val'] < right.attrs['val'])
            if op == 'LE':
                return self._make_bool(left.attrs['val'] <= right.attrs['val'])
            if op == '=':
                if isinstance(left, CoolVoid) and isinstance(right, CoolVoid):
                    return self._make_bool(True)
                if isinstance(left, CoolVoid) or isinstance(right, CoolVoid):
                    return self._make_bool(False)
                if left.class_name in ('Int', 'String', 'Bool'):
                    return self._make_bool(left.attrs['val'] == right.attrs['val'])
                return self._make_bool(left is right)

        if isinstance(expr, Not):
            val = self._eval(expr.expr, self_obj, env)
            return self._make_bool(not val.attrs['val'])

        if isinstance(expr, Negate):
            val = self._eval(expr.expr, self_obj, env)
            return self._make_int(-val.attrs['val'])

        self._runtime_error(0, f"Unknown expression type: {type(expr).__name__}")


# ============================================================
# Main
# ============================================================

def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else '<stdin>'
    tokens = read_tokens()
    parser = Parser(tokens)
    program = parser.parse()
    interp = Interpreter(program, filename)
    interp.run()


if __name__ == '__main__':
    main()
