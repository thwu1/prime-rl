#!/usr/bin/env python3
"""
SMT-LIB 2 Model Validator.
Checks whether a model satisfies all assertions in an SMT-LIB 2 benchmark.
Supports: QF_LIA, QF_NIA, QF_BV, QF_AUFLIA, QF_UFLIA.
"""

import sys


# ── Tokenizer ────────────────────────────────────────────────────────────────

def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == ';':
            while i < n and text[i] != '\n':
                i += 1
        elif c == '(':
            tokens.append('(')
            i += 1
        elif c == ')':
            tokens.append(')')
            i += 1
        elif c == '|':
            j = i + 1
            while j < n and text[j] != '|':
                j += 1
            tokens.append(text[i:j + 1])
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                    else:
                        break
                else:
                    j += 1
            tokens.append(text[i:j + 1])
            i = j + 1
        elif c == '#':
            if i + 1 < n and text[i + 1] in 'xX':
                j = i + 2
                while j < n and text[j] in '0123456789abcdefABCDEF':
                    j += 1
                tokens.append(text[i:j])
                i = j
            elif i + 1 < n and text[i + 1] in 'bB':
                j = i + 2
                while j < n and text[j] in '01':
                    j += 1
                tokens.append(text[i:j])
                i = j
            else:
                j = i + 1
                while j < n and not text[j].isspace() and text[j] not in '()':
                    j += 1
                tokens.append(text[i:j])
                i = j
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '();|"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


# ── S-expression parser ──────────────────────────────────────────────────────

def _parse_one(tokens, pos):
    if pos >= len(tokens):
        return None, pos
    if tokens[pos] == '(':
        lst = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ')':
            item, pos = _parse_one(tokens, pos)
            lst.append(item)
        if pos < len(tokens):
            pos += 1
        return lst, pos
    return tokens[pos], pos + 1


def parse_all(text):
    tokens = tokenize(text)
    result, pos = [], 0
    while pos < len(tokens):
        expr, pos = _parse_one(tokens, pos)
        if expr is not None:
            result.append(expr)
    return result


# ── Value types ──────────────────────────────────────────────────────────────

class BitVec:
    __slots__ = ('val', 'width')

    def __init__(self, val, width):
        self.width = width
        self.val = val & ((1 << width) - 1)

    def signed(self):
        half = 1 << (self.width - 1)
        return self.val - (1 << self.width) if self.val >= half else self.val

    def __eq__(self, other):
        return isinstance(other, BitVec) and self.val == other.val and self.width == other.width

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(('bv', self.val, self.width))

    def __repr__(self):
        return f'BV({self.val},{self.width})'


class ArrayVal:
    __slots__ = ('default', 'entries')

    def __init__(self, default, entries=None):
        self.default = default
        self.entries = dict(entries) if entries else {}

    @staticmethod
    def _key(idx):
        if isinstance(idx, BitVec):
            return ('bv', idx.val, idx.width)
        return idx

    def select(self, idx):
        return self.entries.get(self._key(idx), self.default)

    def store(self, idx, val):
        e = dict(self.entries)
        e[self._key(idx)] = val
        return ArrayVal(self.default, e)

    def __eq__(self, other):
        return (isinstance(other, ArrayVal)
                and self.default == other.default
                and self.entries == other.entries)

    def __hash__(self):
        return hash(id(self))


# ── Evaluator ────────────────────────────────────────────────────────────────

class ModelValidator:
    def __init__(self):
        self.variables = {}
        self.user_funs = {}
        self.refined = {}
        self._refining = set()

    # ── Load benchmark ──

    def load_benchmark(self, text):
        assertions = []
        for s in parse_all(text):
            if isinstance(s, list) and len(s) >= 2:
                if s[0] == 'assert':
                    body = s[1]
                    if isinstance(body, list) and len(body) >= 3 and body[0] == '!':
                        body = body[1]
                    assertions.append(body)
        return assertions

    # ── Load model ──

    def load_model(self, text):
        for s in parse_all(text):
            if not isinstance(s, list) or len(s) == 0:
                continue
            if s[0] == 'model':
                for d in s[1:]:
                    if isinstance(d, list) and len(d) >= 5:
                        self._defn(d)
            elif s[0] in ('define-fun', 'refine-fun'):
                self._defn(s)

    def _defn(self, d):
        kind, name, params = d[0], d[1], d[2]
        body = d[4]
        if kind == 'define-fun':
            if len(params) == 0:
                self.variables[name] = self.ev(body, {})
            else:
                self.user_funs[name] = (params, body)
        elif kind == 'refine-fun':
            self.refined[name] = (params, body)

    # ── Bitvector literal ──

    @staticmethod
    def _bv_lit(atom):
        if atom.startswith('#x') or atom.startswith('#X'):
            h = atom[2:]
            return BitVec(int(h, 16), len(h) * 4)
        if atom.startswith('#b') or atom.startswith('#B'):
            b = atom[2:]
            return BitVec(int(b, 2), len(b))
        return None

    # ── Main evaluator ──

    def ev(self, expr, env):
        if isinstance(expr, str):
            return self._atom(expr, env)
        if isinstance(expr, list):
            return self._compound(expr, env)
        raise ValueError(f'bad expr: {expr!r}')

    def _atom(self, a, env):
        if a in env:
            return env[a]
        if a in self.variables:
            return self.variables[a]
        if a == 'true':
            return True
        if a == 'false':
            return False
        bv = self._bv_lit(a)
        if bv is not None:
            return bv
        try:
            return int(a)
        except ValueError:
            pass
        try:
            return float(a)
        except ValueError:
            pass
        raise ValueError(f'unknown symbol: {a}')

    def _compound(self, expr, env):
        head = expr[0]

        # (_ op ...) applied to arguments
        if isinstance(head, list) and len(head) >= 2 and head[0] == '_':
            return self._indexed_app(head, expr[1:], env)

        # (as name sort) applied to arguments
        if isinstance(head, list) and len(head) >= 2 and head[0] == 'as':
            return self._qualified(head, expr[1:], env)

        # standalone (_ bvN W)
        if head == '_' and len(expr) >= 3 and isinstance(expr[1], str) and expr[1].startswith('bv'):
            return BitVec(int(expr[1][2:]), int(expr[2]))

        if not isinstance(head, str):
            raise ValueError(f'unexpected head: {head!r}')

        # ── Special forms ──
        if head == 'let':
            new = dict(env)
            for b in expr[1]:
                new[b[0]] = self.ev(b[1], env)
            return self.ev(expr[2], new)

        if head == 'ite':
            return self.ev(expr[2] if self.ev(expr[1], env) else expr[3], env)

        if head == '!':
            return self.ev(expr[1], env)

        # ── Boolean ──
        if head == 'and':
            return all(self.ev(a, env) for a in expr[1:])
        if head == 'or':
            return any(self.ev(a, env) for a in expr[1:])
        if head == 'not':
            return not self.ev(expr[1], env)
        if head == '=>':
            return (not self.ev(expr[1], env)) or self.ev(expr[2], env)
        if head == 'xor':
            return self.ev(expr[1], env) != self.ev(expr[2], env)

        # ── Equality ──
        if head == '=':
            vs = [self.ev(a, env) for a in expr[1:]]
            return all(v == vs[0] for v in vs[1:])
        if head == 'distinct':
            vs = [self.ev(a, env) for a in expr[1:]]
            for i in range(len(vs)):
                for j in range(i + 1, len(vs)):
                    if vs[i] == vs[j]:
                        return False
            return True

        # ── Integer arithmetic ──
        if head == '+':
            return sum(self.ev(a, env) for a in expr[1:])
        if head == '-':
            if len(expr) == 2:
                return -self.ev(expr[1], env)
            return self.ev(expr[1], env) - self.ev(expr[2], env)
        if head == '*':
            r = 1
            for a in expr[1:]:
                r *= self.ev(a, env)
            return r
        if head == 'abs':
            return abs(self.ev(expr[1], env))

        # ── div / mod with refinement support ──
        if head == 'div':
            return self._maybe_refined('div', expr[1:], env, self._t_div)
        if head == 'mod':
            return self._maybe_refined('mod', expr[1:], env, self._t_mod)

        # ── Integer comparisons ──
        if head == '<':
            return self.ev(expr[1], env) < self.ev(expr[2], env)
        if head == '<=':
            return self.ev(expr[1], env) <= self.ev(expr[2], env)
        if head == '>':
            return self.ev(expr[1], env) > self.ev(expr[2], env)
        if head == '>=':
            return self.ev(expr[1], env) >= self.ev(expr[2], env)

        # ── Bitvector ──
        r = self._bv_op(head, expr[1:], env)
        if r is not None:
            return r

        # ── Array ──
        if head == 'select':
            return self.ev(expr[1], env).select(self.ev(expr[2], env))
        if head == 'store':
            return self.ev(expr[1], env).store(self.ev(expr[2], env), self.ev(expr[3], env))

        # ── User / refined function call ──
        args = [self.ev(a, env) for a in expr[1:]]
        return self._call_fun(head, args, env)

    # ── Indexed application: ((_ extract i j) x) etc. ──

    def _indexed_app(self, head, raw_args, env):
        op = head[1]
        if op == 'extract':
            hi, lo = int(head[2]), int(head[3])
            x = self.ev(raw_args[0], env)
            mask = (1 << (hi - lo + 1)) - 1
            return BitVec((x.val >> lo) & mask, hi - lo + 1)
        if op == 'zero_extend':
            ext = int(head[2])
            x = self.ev(raw_args[0], env)
            return BitVec(x.val, x.width + ext)
        if op == 'sign_extend':
            ext = int(head[2])
            x = self.ev(raw_args[0], env)
            return BitVec(x.signed(), x.width + ext)
        if op == 'repeat':
            cnt = int(head[2])
            x = self.ev(raw_args[0], env)
            v = 0
            for i in range(cnt):
                v |= x.val << (i * x.width)
            return BitVec(v, x.width * cnt)
        if op == 'rotate_left':
            amt = int(head[2])
            x = self.ev(raw_args[0], env)
            w = x.width
            amt %= w
            return BitVec(((x.val << amt) | (x.val >> (w - amt))), w)
        if op == 'rotate_right':
            amt = int(head[2])
            x = self.ev(raw_args[0], env)
            w = x.width
            amt %= w
            return BitVec(((x.val >> amt) | (x.val << (w - amt))), w)
        # (_ bvN W) used as function head? shouldn't happen, treat as value
        if op.startswith('bv'):
            return BitVec(int(op[2:]), int(head[2]))
        raise ValueError(f'unknown indexed op: {op}')

    # ── Qualified identifier: (as const (Array K V)) ──

    def _qualified(self, head, args, env):
        name = head[1]
        if name == 'const':
            val = self.ev(args[0], env)
            return ArrayVal(val)
        raise ValueError(f'unknown qualified id: {head}')

    # ── Bitvector operations ──

    _BV_OPS = frozenset({
        'bvadd', 'bvsub', 'bvmul', 'bvudiv', 'bvurem', 'bvsrem', 'bvsmod',
        'bvand', 'bvor', 'bvxor', 'bvnot', 'bvneg',
        'bvshl', 'bvlshr', 'bvashr',
        'bvult', 'bvule', 'bvugt', 'bvuge',
        'bvslt', 'bvsle', 'bvsgt', 'bvsge',
        'concat', 'bvcomp',
    })

    def _bv_op(self, op, raw_args, env):
        if op not in self._BV_OPS:
            return None
        args = [self.ev(a, env) for a in raw_args]

        if op == 'bvadd':
            return BitVec(args[0].val + args[1].val, args[0].width)
        if op == 'bvsub':
            return BitVec(args[0].val - args[1].val, args[0].width)
        if op == 'bvmul':
            return BitVec(args[0].val * args[1].val, args[0].width)
        if op == 'bvudiv':
            b = args[1].val
            return BitVec((1 << args[0].width) - 1 if b == 0 else args[0].val // b,
                          args[0].width)
        if op == 'bvurem':
            b = args[1].val
            return BitVec(args[0].val if b == 0 else args[0].val % b, args[0].width)
        if op == 'bvsrem':
            a_s, b_s = args[0].signed(), args[1].signed()
            if b_s == 0:
                return args[0]
            r = abs(a_s) % abs(b_s)
            return BitVec(-r if a_s < 0 else r, args[0].width)
        if op == 'bvsmod':
            a_s, b_s = args[0].signed(), args[1].signed()
            if b_s == 0:
                return args[0]
            r = abs(a_s) % abs(b_s)
            if r == 0:
                return BitVec(0, args[0].width)
            if a_s >= 0 and b_s > 0:
                return BitVec(r, args[0].width)
            if a_s < 0 and b_s > 0:
                return BitVec(b_s - r, args[0].width)
            if a_s >= 0 and b_s < 0:
                return BitVec(b_s + r, args[0].width)
            return BitVec(-r, args[0].width)

        if op == 'bvand':
            return BitVec(args[0].val & args[1].val, args[0].width)
        if op == 'bvor':
            return BitVec(args[0].val | args[1].val, args[0].width)
        if op == 'bvxor':
            return BitVec(args[0].val ^ args[1].val, args[0].width)
        if op == 'bvnot':
            return BitVec(~args[0].val, args[0].width)
        if op == 'bvneg':
            return BitVec(-args[0].val, args[0].width)

        if op == 'bvshl':
            s = args[1].val
            w = args[0].width
            return BitVec(0 if s >= w else args[0].val << s, w)
        if op == 'bvlshr':
            s = args[1].val
            w = args[0].width
            return BitVec(0 if s >= w else args[0].val >> s, w)
        if op == 'bvashr':
            s = args[1].val
            w = args[0].width
            sv = args[0].signed()
            if s >= w:
                return BitVec(-1 if sv < 0 else 0, w)
            return BitVec(sv >> s, w)

        if op == 'bvult':
            return args[0].val < args[1].val
        if op == 'bvule':
            return args[0].val <= args[1].val
        if op == 'bvugt':
            return args[0].val > args[1].val
        if op == 'bvuge':
            return args[0].val >= args[1].val
        if op == 'bvslt':
            return args[0].signed() < args[1].signed()
        if op == 'bvsle':
            return args[0].signed() <= args[1].signed()
        if op == 'bvsgt':
            return args[0].signed() > args[1].signed()
        if op == 'bvsge':
            return args[0].signed() >= args[1].signed()

        if op == 'concat':
            a, b = args[0], args[1]
            return BitVec((a.val << b.width) | b.val, a.width + b.width)
        if op == 'bvcomp':
            return BitVec(1 if args[0].val == args[1].val else 0, 1)

        return None  # unreachable

    # ── Theory div / mod (Euclidean) ──

    @staticmethod
    def _t_div(a, b):
        if b == 0:
            return 0
        if b > 0:
            return a // b  # Python floor division is correct for positive b
        return -(a // (-b))

    @staticmethod
    def _t_mod(a, b):
        if b == 0:
            return 0
        d = ModelValidator._t_div(a, b)
        return a - b * d

    # ── Refined / user function dispatch ──

    def _maybe_refined(self, name, raw_args, env, theory_fn):
        args = [self.ev(a, env) for a in raw_args]
        if name in self.refined and name not in self._refining:
            params, body = self.refined[name]
            new_env = dict(env)
            for p, v in zip(params, args):
                new_env[p[0]] = v
            self._refining.add(name)
            try:
                return self.ev(body, new_env)
            finally:
                self._refining.discard(name)
        return theory_fn(*args)

    def _call_fun(self, name, args, env):
        if name in self.user_funs:
            params, body = self.user_funs[name]
            new_env = dict(env)
            for p, v in zip(params, args):
                new_env[p[0]] = v
            return self.ev(body, new_env)
        if name in self.refined and name not in self._refining:
            params, body = self.refined[name]
            new_env = dict(env)
            for p, v in zip(params, args):
                new_env[p[0]] = v
            self._refining.add(name)
            try:
                return self.ev(body, new_env)
            finally:
                self._refining.discard(name)
        raise ValueError(f'unknown function: {name}')

    # ── Top-level validation ──

    def validate(self, bench_text, model_text):
        assertions = self.load_benchmark(bench_text)
        self.load_model(model_text)
        for a in assertions:
            try:
                if self.ev(a, {}) is not True:
                    return False
            except Exception:
                return False
        return True


def main():
    if len(sys.argv) != 3:
        print('Usage: python3 validate_model.py <benchmark.smt2> <model.smt2>',
              file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        bench = f.read()
    with open(sys.argv[2]) as f:
        model = f.read()
    v = ModelValidator()
    print('VALID' if v.validate(bench, model) else 'INVALID')


if __name__ == '__main__':
    main()
