#!/usr/bin/env python3
"""SysY Language Interpreter."""
import sys

# ======================== LEXER ========================

KEYWORDS = {'const', 'int', 'void', 'if', 'else', 'while',
            'break', 'continue', 'return'}
TWO_CHAR_OPS = {'<=', '>=', '==', '!=', '&&', '||'}
SINGLE_CHARS = set('+-*/%<>=!()[]{}:;,')


def tokenize(src):
    toks, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in ' \t\r\n':
            i += 1
        elif src[i:i+2] == '//':
            i = src.find('\n', i)
            if i < 0:
                i = n
        elif src[i:i+2] == '/*':
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c.isdigit():
            j = i
            if c == '0' and i+1 < n and src[i+1] in 'xX':
                i += 2
                while i < n and src[i] in '0123456789abcdefABCDEF':
                    i += 1
                toks.append(('NUM', int(src[j:i], 16)))
            elif c == '0' and i+1 < n and src[i+1] in '01234567':
                i += 1
                while i < n and src[i] in '01234567':
                    i += 1
                toks.append(('NUM', int(src[j:i], 8)))
            else:
                while i < n and src[i].isdigit():
                    i += 1
                toks.append(('NUM', int(src[j:i])))
        elif c.isalpha() or c == '_':
            j = i
            while i < n and (src[i].isalnum() or src[i] == '_'):
                i += 1
            w = src[j:i]
            toks.append(('KW' if w in KEYWORDS else 'ID', w))
        elif src[i:i+2] in TWO_CHAR_OPS:
            toks.append(('OP', src[i:i+2]))
            i += 2
        elif c in SINGLE_CHARS:
            toks.append(('OP', c))
            i += 1
        else:
            i += 1
    toks.append(('EOF', None))
    return toks

# ======================== PARSER ========================


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.p = 0

    def cur(self):
        return self.toks[self.p]

    def peek(self, val=None):
        t = self.cur()
        if val is None:
            return t
        return t[1] == val

    def eat(self, val=None):
        t = self.cur()
        if val is not None and t[1] != val:
            raise SyntaxError(f"Expected '{val}', got '{t[1]}' at token {self.p}")
        self.p += 1
        return t[1]

    def at(self, val):
        return self.cur()[1] == val

    # ---- top level ----

    def parse(self):
        decls, funcs = [], []
        while not self.at(None):
            is_const = self.at('const')
            if is_const:
                decls.append(self.p_const_decl())
                continue
            # int or void
            ty = self.eat()  # 'int' or 'void'
            name = self.eat()  # IDENT
            if self.at('('):
                funcs.append(self.p_func_def(ty, name))
            else:
                decls.extend(self.p_var_decl_rest(name))
        return ('program', decls, funcs)

    # ---- declarations ----

    def p_const_decl(self):
        self.eat('const')
        self.eat('int')
        defs = [self.p_const_def()]
        while self.at(','):
            self.eat(',')
            defs.append(self.p_const_def())
        self.eat(';')
        return ('const_decl', defs)

    def p_const_def(self):
        name = self.eat()
        dims = self.p_dims()
        self.eat('=')
        init = self.p_const_init()
        return (name, dims, init)

    def p_const_init(self):
        if self.at('{'):
            self.eat('{')
            items = []
            if not self.at('}'):
                items.append(self.p_const_init())
                while self.at(','):
                    self.eat(',')
                    if self.at('}'):
                        break
                    items.append(self.p_const_init())
            self.eat('}')
            return ('arr_init', items)
        return self.p_exp()

    def p_var_decl(self):
        self.eat('int')
        name = self.eat()
        return self.p_var_decl_rest(name)

    def p_var_decl_rest(self, first_name):
        defs = [self.p_var_def(first_name)]
        while self.at(','):
            self.eat(',')
            name = self.eat()
            defs.append(self.p_var_def(name))
        self.eat(';')
        return [('var_decl', d) for d in defs]

    def p_var_def(self, name):
        dims = self.p_dims()
        init = None
        if self.at('='):
            self.eat('=')
            init = self.p_init_val()
        return (name, dims, init)

    def p_init_val(self):
        if self.at('{'):
            self.eat('{')
            items = []
            if not self.at('}'):
                items.append(self.p_init_val())
                while self.at(','):
                    self.eat(',')
                    if self.at('}'):
                        break
                    items.append(self.p_init_val())
            self.eat('}')
            return ('arr_init', items)
        return self.p_exp()

    def p_dims(self):
        dims = []
        while self.at('['):
            self.eat('[')
            dims.append(self.p_exp())
            self.eat(']')
        return dims

    # ---- functions ----

    def p_func_def(self, ret_type, name):
        self.eat('(')
        params = []
        if not self.at(')'):
            params.append(self.p_func_param())
            while self.at(','):
                self.eat(',')
                params.append(self.p_func_param())
        self.eat(')')
        body = self.p_block()
        return ('func', ret_type, name, params, body)

    def p_func_param(self):
        self.eat('int')
        name = self.eat()
        dims = []
        if self.at('['):
            self.eat('[')
            self.eat(']')
            dims.append(None)  # first dim omitted
            while self.at('['):
                self.eat('[')
                dims.append(self.p_exp())
                self.eat(']')
        return (name, dims)

    # ---- statements ----

    def p_block(self):
        self.eat('{')
        items = []
        while not self.at('}'):
            items.extend(self.p_block_item())
        self.eat('}')
        return ('block', items)

    def p_block_item(self):
        if self.at('const'):
            return [self.p_const_decl()]
        if self.at('int'):
            return self.p_var_decl()
        return [self.p_stmt()]

    def p_stmt(self):
        if self.at('{'):
            return self.p_block()
        if self.at('if'):
            return self.p_if()
        if self.at('while'):
            return self.p_while()
        if self.at('break'):
            self.eat('break')
            self.eat(';')
            return ('break',)
        if self.at('continue'):
            self.eat('continue')
            self.eat(';')
            return ('continue',)
        if self.at('return'):
            self.eat('return')
            val = None
            if not self.at(';'):
                val = self.p_exp()
            self.eat(';')
            return ('return', val)
        if self.at(';'):
            self.eat(';')
            return ('nop',)
        # assignment or expression stmt
        saved = self.p
        try:
            lval = self.p_lval()
            if self.at('='):
                self.eat('=')
                exp = self.p_exp()
                self.eat(';')
                return ('assign', lval, exp)
        except Exception:
            pass
        self.p = saved
        exp = self.p_exp()
        self.eat(';')
        return ('exp_stmt', exp)

    def p_if(self):
        self.eat('if')
        self.eat('(')
        cond = self.p_exp()
        self.eat(')')
        then = self.p_stmt()
        els = None
        if self.at('else'):
            self.eat('else')
            els = self.p_stmt()
        return ('if', cond, then, els)

    def p_while(self):
        self.eat('while')
        self.eat('(')
        cond = self.p_exp()
        self.eat(')')
        body = self.p_stmt()
        return ('while', cond, body)

    # ---- expressions ----

    def p_exp(self):
        return self.p_lor()

    def p_lor(self):
        left = self.p_land()
        while self.at('||'):
            self.eat('||')
            right = self.p_land()
            left = ('||', left, right)
        return left

    def p_land(self):
        left = self.p_eq()
        while self.at('&&'):
            self.eat('&&')
            right = self.p_eq()
            left = ('&&', left, right)
        return left

    def p_eq(self):
        left = self.p_rel()
        while self.cur()[1] in ('==', '!='):
            op = self.eat()
            right = self.p_rel()
            left = (op, left, right)
        return left

    def p_rel(self):
        left = self.p_add()
        while self.cur()[1] in ('<', '>', '<=', '>='):
            op = self.eat()
            right = self.p_add()
            left = (op, left, right)
        return left

    def p_add(self):
        left = self.p_mul()
        while self.cur()[1] in ('+', '-'):
            op = self.eat()
            right = self.p_mul()
            left = (op, left, right)
        return left

    def p_mul(self):
        left = self.p_unary()
        while self.cur()[1] in ('*', '/', '%'):
            op = self.eat()
            right = self.p_unary()
            left = (op, left, right)
        return left

    def p_unary(self):
        if self.cur()[1] in ('+', '-', '!'):
            op = self.eat()
            operand = self.p_unary()
            return ('unary_' + op, operand)
        # function call: ID '('
        if self.cur()[0] == 'ID':
            saved = self.p
            name = self.eat()
            if self.at('('):
                self.eat('(')
                args = []
                if not self.at(')'):
                    args.append(self.p_exp())
                    while self.at(','):
                        self.eat(',')
                        args.append(self.p_exp())
                self.eat(')')
                return ('call', name, args)
            self.p = saved
        return self.p_primary()

    def p_primary(self):
        if self.at('('):
            self.eat('(')
            e = self.p_exp()
            self.eat(')')
            return e
        if self.cur()[0] == 'NUM':
            return ('num', self.eat())
        return self.p_lval()

    def p_lval(self):
        if self.cur()[0] not in ('ID',):
            raise SyntaxError(f"Expected identifier, got {self.cur()}")
        name = self.eat()
        indices = []
        while self.at('['):
            self.eat('[')
            indices.append(self.p_exp())
            self.eat(']')
        if indices:
            return ('idx', name, indices)
        return ('var', name)

# ======================== RUNTIME ========================


def i32(v):
    v = int(v) & 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def c_div(a, b):
    s = -1 if (a < 0) != (b < 0) else 1
    return s * (abs(a) // abs(b))


def c_mod(a, b):
    return a - c_div(a, b) * b


class BreakSig(Exception):
    pass


class ContSig(Exception):
    pass


class RetSig(Exception):
    def __init__(self, v):
        self.v = v


class SysYArray:
    """Flat-storage multi-dimensional array."""
    def __init__(self, dims, data=None):
        self.dims = dims
        sz = 1
        for d in dims:
            sz *= d
        self.data = data if data else [0] * sz

    def _flat(self, indices):
        idx = 0
        for i, ix in enumerate(indices):
            stride = 1
            for j in range(i + 1, len(self.dims)):
                stride *= self.dims[j]
            idx += ix * stride
        return idx

    def get(self, indices):
        return self.data[self._flat(indices)]

    def set(self, indices, val):
        self.data[self._flat(indices)] = val

    def sub_array(self, index):
        """Return a sub-array view for passing to functions."""
        stride = 1
        for d in self.dims[1:]:
            stride *= d
        start = index * stride
        return SysYArray(self.dims[1:], self.data[start:start+stride])


# ======================== EVALUATOR ========================


class Env:
    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}
        self.consts = {}

    def define(self, name, val):
        self.vars[name] = val

    def define_const(self, name, val):
        self.consts[name] = val

    def lookup(self, name):
        if name in self.vars:
            return self
        if name in self.consts:
            return self
        if self.parent:
            return self.parent.lookup(name)
        raise NameError(f"Undefined variable: {name}")

    def get(self, name):
        env = self.lookup(name)
        if name in env.consts:
            return env.consts[name]
        return env.vars[name]

    def set(self, name, val):
        env = self.lookup(name)
        env.vars[name] = val


class Interp:
    def __init__(self):
        self.global_env = Env()
        self.funcs = {}
        self._stdin_buf = None
        self._stdin_pos = 0

    def _read_stdin(self):
        if self._stdin_buf is None:
            self._stdin_buf = sys.stdin.read()

    def _getint(self):
        self._read_stdin()
        while (self._stdin_pos < len(self._stdin_buf) and
               self._stdin_buf[self._stdin_pos] in ' \t\r\n'):
            self._stdin_pos += 1
        s = ''
        if (self._stdin_pos < len(self._stdin_buf) and
                self._stdin_buf[self._stdin_pos] in '+-'):
            s += self._stdin_buf[self._stdin_pos]
            self._stdin_pos += 1
        while (self._stdin_pos < len(self._stdin_buf) and
               self._stdin_buf[self._stdin_pos].isdigit()):
            s += self._stdin_buf[self._stdin_pos]
            self._stdin_pos += 1
        return int(s) if s else 0

    def _getch(self):
        self._read_stdin()
        if self._stdin_pos < len(self._stdin_buf):
            c = self._stdin_buf[self._stdin_pos]
            self._stdin_pos += 1
            return ord(c)
        return -1

    def run(self, tree):
        _, decls, funcs = tree
        # Register functions
        for f in funcs:
            self.funcs[f[2]] = f
        # Process global declarations
        for d in decls:
            self.exec_decl(d, self.global_env, is_global=True)
        # Call main
        if 'main' not in self.funcs:
            raise RuntimeError("No main function")
        return self.call_func('main', [])

    def exec_decl(self, node, env, is_global=False):
        if node[0] == 'var_decl':
            name, dims, init = node[1]
            if dims:
                dim_vals = [self.eval_exp(d, env) for d in dims]
                arr = SysYArray(dim_vals)
                if init:
                    self._fill_array(arr, [], dim_vals, init, env)
                env.define(name, arr)
            else:
                if init:
                    val = self.eval_exp(init, env)
                else:
                    val = 0 if is_global else 0
                env.define(name, i32(val))
        elif node[0] == 'const_decl':
            for (name, dims, init) in node[1]:
                if dims:
                    dim_vals = [self.eval_exp(d, env) for d in dims]
                    arr = SysYArray(dim_vals)
                    if init:
                        self._fill_array(arr, [], dim_vals, init, env)
                    env.define_const(name, arr)
                else:
                    val = self.eval_exp(init, env)
                    env.define_const(name, i32(val))

    def _fill_array(self, arr, prefix, rem_dims, init, env):
        if init[0] != 'arr_init':
            # Scalar value at this position
            arr.set(prefix, i32(self.eval_exp(init, env)))
            return
        items = init[1]
        if len(rem_dims) == 1:
            for i, item in enumerate(items):
                val = self.eval_exp(item, env) if item[0] != 'arr_init' else 0
                arr.set(prefix + [i], i32(val))
        else:
            for i, item in enumerate(items):
                self._fill_array(arr, prefix + [i], rem_dims[1:], item, env)

    def exec_stmt(self, node, env):
        t = node[0]
        if t == 'block':
            child_env = Env(env)
            for item in node[1]:
                self.exec_stmt(item, child_env)
        elif t == 'var_decl' or t == 'const_decl':
            self.exec_decl(node, env)
        elif t == 'assign':
            lval, exp = node[1], node[2]
            val = i32(self.eval_exp(exp, env))
            if lval[0] == 'var':
                env.set(lval[1], val)
            elif lval[0] == 'idx':
                name, indices = lval[1], lval[2]
                arr = env.get(name)
                idx_vals = [self.eval_exp(ix, env) for ix in indices]
                arr.set(idx_vals, val)
        elif t == 'if':
            cond_val = self.eval_exp(node[1], env)
            if cond_val != 0:
                self.exec_stmt(node[2], env)
            elif node[3] is not None:
                self.exec_stmt(node[3], env)
        elif t == 'while':
            while True:
                cond_val = self.eval_exp(node[1], env)
                if cond_val == 0:
                    break
                try:
                    self.exec_stmt(node[2], env)
                except BreakSig:
                    break
                except ContSig:
                    continue
        elif t == 'break':
            raise BreakSig()
        elif t == 'continue':
            raise ContSig()
        elif t == 'return':
            val = self.eval_exp(node[1], env) if node[1] is not None else 0
            raise RetSig(i32(val))
        elif t == 'exp_stmt':
            self.eval_exp(node[1], env)
        elif t == 'nop':
            pass

    def eval_exp(self, node, env):
        t = node[0]
        if t == 'num':
            return node[1]
        elif t == 'var':
            return env.get(node[1])
        elif t == 'idx':
            arr = env.get(node[1])
            indices = [self.eval_exp(ix, env) for ix in node[2]]
            return arr.get(indices)
        elif t == 'call':
            return self._do_call(node[1], node[2], env)
        elif t == 'unary_+':
            return self.eval_exp(node[1], env)
        elif t == 'unary_-':
            return i32(-self.eval_exp(node[1], env))
        elif t == 'unary_!':
            return 1 if self.eval_exp(node[1], env) == 0 else 0
        elif t == '||':
            left = self.eval_exp(node[1], env)
            if left != 0:
                return 1
            return 1 if self.eval_exp(node[2], env) != 0 else 0
        elif t == '&&':
            left = self.eval_exp(node[1], env)
            if left == 0:
                return 0
            return 1 if self.eval_exp(node[2], env) != 0 else 0
        elif t in ('+', '-', '*', '/', '%', '<', '>', '<=', '>=', '==', '!='):
            a = self.eval_exp(node[1], env)
            b = self.eval_exp(node[2], env)
            return self._binop(t, a, b)
        raise RuntimeError(f"Unknown node: {t}")

    def _binop(self, op, a, b):
        if op == '+': return i32(a + b)
        if op == '-': return i32(a - b)
        if op == '*': return i32(a * b)
        if op == '/': return i32(c_div(a, b))
        if op == '%': return i32(c_mod(a, b))
        if op == '<': return 1 if a < b else 0
        if op == '>': return 1 if a > b else 0
        if op == '<=': return 1 if a <= b else 0
        if op == '>=': return 1 if a >= b else 0
        if op == '==': return 1 if a == b else 0
        if op == '!=': return 1 if a != b else 0
        raise RuntimeError(f"Unknown op: {op}")

    def _do_call(self, name, args, env):
        arg_vals = [self.eval_exp(a, env) for a in args]
        # Builtins
        if name == 'getint':
            return self._getint()
        if name == 'getch':
            return self._getch()
        if name == 'getarray':
            n = self._getint()
            arr = arg_vals[0] if isinstance(arg_vals[0], SysYArray) else env.get(args[0][1])
            for ii in range(n):
                arr.set([ii], self._getint())
            return n
        if name == 'putint':
            print(arg_vals[0], end='')
            return 0
        if name == 'putch':
            print(chr(arg_vals[0]), end='')
            return 0
        if name == 'putarray':
            n = arg_vals[0]
            arr = arg_vals[1] if isinstance(arg_vals[1], SysYArray) else None
            if arr:
                print(f"{n}:", end='')
                for ii in range(n):
                    print(f" {arr.get([ii])}", end='')
                print()
            return 0
        # User function
        if name not in self.funcs:
            raise RuntimeError(f"Undefined function: {name}")
        func = self.funcs[name]
        _, ret_type, fname, params, body = func
        call_env = Env(self.global_env)
        for i, (pname, pdims) in enumerate(params):
            if i < len(arg_vals):
                call_env.define(pname, arg_vals[i])
            else:
                call_env.define(pname, 0)
        try:
            self.exec_stmt(body, call_env)
        except RetSig as r:
            return r.v
        return 0

    def call_func(self, name, args):
        return self._do_call(name, [('num', a) for a in args], self.global_env)


# ======================== MAIN ========================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_run <source.sy>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], 'r') as f:
        src = f.read()
    toks = tokenize(src)
    parser = Parser(toks)
    tree = parser.parse()
    interp = Interp()
    ret = interp.run(tree)
    sys.exit(ret & 0xFF)


if __name__ == '__main__':
    main()
