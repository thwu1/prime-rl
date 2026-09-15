#!/usr/bin/env python3
"""
DaeDaLus DDL-to-C transpiler.
Usage: python3 ddl_transpile.py <spec.ddl> <output.c>

Parses a .ddl specification file and generates C source that, when compiled
against parser.h / runtime.c, produces a binary format parser outputting JSON.
"""
import sys
import re


# ======================================================================
# AST Node Types
# ======================================================================

class N:
    pass

class Block(N):
    def __init__(self, stmts):
        self.stmts = stmts

class Prim(N):
    def __init__(self, name):
        self.name = name

class MatchB(N):
    def __init__(self, vals):
        self.vals = vals

class MatchS(N):
    def __init__(self, text):
        self.text = text

class End(N):
    pass

class ManyN(N):
    def __init__(self, count, parser):
        self.count = count
        self.parser = parser

class CaseN(N):
    def __init__(self, expr, branches):
        self.expr = expr
        self.branches = branches

class Tagged(N):
    def __init__(self, tag, val):
        self.tag = tag
        self.val = val

class FirstN(N):
    def __init__(self, alts):
        self.alts = alts

class Choice(N):
    def __init__(self, left, right):
        self.left = left
        self.right = right

class ChunkN(N):
    def __init__(self, size, parser):
        self.size = size
        self.parser = parser

class GuardN(N):
    def __init__(self, cond):
        self.cond = cond

class Call(N):
    def __init__(self, name):
        self.name = name

class Coerce(N):
    def __init__(self, inner):
        self.inner = inner

class Lit(N):
    def __init__(self, v):
        self.v = v

class Var(N):
    def __init__(self, name):
        self.name = name

class FAcc(N):
    def __init__(self, obj, field):
        self.obj = obj
        self.field = field

class BinOp(N):
    def __init__(self, op, l, r):
        self.op = op
        self.l = l
        self.r = r


# ======================================================================
# DDL Source Parser
# ======================================================================

def strip_comments(src):
    while '{-' in src:
        start = src.index('{-')
        depth, i = 1, start + 2
        while i < len(src) and depth > 0:
            if src[i:i+2] == '{-':
                depth += 1; i += 2
            elif src[i:i+2] == '-}':
                depth -= 1; i += 2
            else:
                i += 1
        src = src[:start] + src[i:]
    out = []
    for line in src.split('\n'):
        p = line.find('--')
        out.append(line[:p] if p >= 0 else line)
    return '\n'.join(out)


def get_lines(src):
    result = []
    for i, line in enumerate(src.split('\n')):
        s = line.rstrip()
        c = s.lstrip()
        if c:
            result.append((len(s) - len(c), c, i + 1))
    return result


def gather(lines, start, min_indent):
    body, i = [], start
    while i < len(lines) and lines[i][0] > min_indent:
        body.append(lines[i])
        i += 1
    return body, i


def parse_defs(src):
    src = strip_comments(src)
    lines = get_lines(src)
    defs = {}
    i = 0
    while i < len(lines):
        ind, c, ln = lines[i]
        m = re.match(r'def\s+(\w+)\s*=\s*(.*)', c)
        if m:
            name, rest = m.group(1), m.group(2).strip()
            body, j = gather(lines, i + 1, ind)
            if rest:
                body = [(ind + 2, rest, ln)] + body
            defs[name] = parse_node(body)
            i = j
        else:
            i += 1
    return defs


def parse_node(lines):
    if not lines:
        raise Exception("empty body")
    _, c, _ = lines[0]
    if c == 'block':
        return parse_block(lines[1:])
    if c == 'First':
        return parse_first(lines[1:])
    if c.startswith('case '):
        return parse_case(lines)
    return parse_inline(c, lines[1:], lines[0][0])


def parse_block(lines):
    if not lines:
        return Block([])
    bi = lines[0][0]
    stmts = []
    i = 0
    while i < len(lines):
        ind, c, ln = lines[i]
        if ind < bi:
            break
        sub, j = gather(lines, i + 1, ind)
        stmts.append(parse_stmt(c, sub, ind))
        i = j
    return Block(stmts)


def find_eq(s):
    depth = 0
    i = 0
    in_str = False
    while i < len(s):
        c = s[i]
        if c == '"':
            in_str = not in_str
        if in_str:
            i += 1
            continue
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == '=' and depth == 0:
            if i + 1 < len(s) and s[i+1] == '=':
                i += 2
                continue
            if i > 0 and s[i-1] in '<!>':
                i += 1
                continue
            pre = s[:i].strip()
            excluded = ('Match', 'Guard', 'END', 'Many', 'Chunk',
                        'UInt', 'BE', 'LE', '{|', 'case', 'Fail')
            if any(pre.startswith(p) for p in excluded):
                i += 1
                continue
            if re.match(r'^[A-Z]\w+$', pre):
                i += 1
                continue
            return i
        i += 1
    return None


def parse_stmt(content, sub_lines, indent):
    if content.startswith('let ') and '=' in content:
        m = re.match(r'let\s+(\w+)\s*=\s*(.*)', content)
        return ('let', m.group(1),
                parse_inline(m.group(2).strip(), sub_lines, indent))
    if content.startswith('$$'):
        r = re.match(r'\$\$\s*=\s*(.*)', content)
        return ('result', None,
                parse_inline(r.group(1).strip(), sub_lines, indent))
    if content.startswith('@'):
        return ('suppress', None,
                parse_inline(content[1:].strip(), sub_lines, indent))
    eq = find_eq(content)
    if eq is not None:
        name = content[:eq].strip()
        expr = content[eq+1:].strip()
        return ('field', name, parse_inline(expr, sub_lines, indent))
    return ('exec', None, parse_inline(content, sub_lines, indent))


def parse_first(lines):
    if not lines:
        return FirstN([])
    fi = lines[0][0]
    alts = []
    i = 0
    while i < len(lines):
        ind, c, _ = lines[i]
        if ind < fi:
            break
        m = re.match(r'(\w+)\s*=\s*(.*)', c)
        if m:
            sub, j = gather(lines, i + 1, ind)
            alts.append((m.group(1),
                         parse_inline(m.group(2).strip(), sub, ind)))
            i = j
        else:
            i += 1
    return FirstN(alts)


def parse_case(lines):
    m = re.match(r'case\s+(.+?)\s+of\s*$', lines[0][1])
    if not m:
        raise Exception(f"Bad case: {lines[0][1]}")
    expr = parse_sexpr(m.group(1).strip())
    cl = lines[1:]
    if not cl:
        raise Exception("empty case")
    ci = cl[0][0]
    branches = []
    i = 0
    while i < len(cl):
        ind, c, _ = cl[i]
        if ind < ci:
            break
        am = re.match(r'(.+?)\s*->\s*(.*)', c)
        if am:
            ps = am.group(1).strip()
            if ps == '_':
                pat = '_'
            elif ps.startswith('0x') or ps.startswith('0X'):
                pat = int(ps, 16)
            else:
                pat = int(ps)
            sub, j = gather(cl, i + 1, ind)
            branches.append((pat,
                             parse_inline(am.group(2).strip(), sub, ind)))
            i = j
        else:
            i += 1
    return CaseN(expr, branches)


def parse_inline(content, extra=None, indent=0):
    if not extra:
        extra = []
    if not content:
        if extra:
            return parse_node(extra)
        raise Exception("empty inline")
    if ' <| ' in content:
        parts = content.split(' <| ', 1)
        return Choice(parse_inline(parts[0].strip()),
                      parse_inline(parts[1].strip(), extra, indent))
    cm = re.match(r'^(.+?)\s+as[?!]?\s+uint\s+\d+$', content)
    if cm:
        return Coerce(parse_inline(cm.group(1).strip()))
    cm2 = re.match(r'^(.+?)\s+as[?!]?\s+int$', content)
    if cm2:
        return Coerce(parse_inline(cm2.group(1).strip()))
    if content == 'block':
        return parse_block(extra)
    if content == 'First':
        return parse_first(extra)
    if content.startswith('case '):
        return parse_case([(indent, content, 0)] + extra)
    tm = re.match(r'^\{\|\s*(\w+)\s*=\s*(.*?)\s*\|\}$', content)
    if tm:
        return Tagged(tm.group(1), parse_inline(tm.group(2).strip()))
    if content.startswith('Match '):
        rest = content[6:].strip()
        if rest.startswith('['):
            bs = rest[1:rest.rindex(']')]
            vals = []
            for b in bs.split(','):
                b = b.strip()
                if not b:
                    continue
                vals.append(int(b, 16) if b.startswith(('0x', '0X')) else int(b))
            return MatchB(vals)
        if rest.startswith('"'):
            return MatchS(rest[1:rest.rindex('"')])
    if content.startswith('Guard '):
        rest = content[6:].strip()
        if rest.startswith('(') and rest.endswith(')'):
            rest = rest[1:-1]
        return GuardN(parse_sexpr(rest))
    if content.startswith('Many '):
        rest = content[5:].strip()
        tokens = rest.split(None, 1)
        if len(tokens) >= 2:
            first = tokens[0]
            if re.match(r'^(\d+|0x[\da-fA-F]+)$', first):
                n = int(first, 16) if first.startswith('0x') else int(first)
                return ManyN(Lit(n), parse_inline(tokens[1]))
            if re.match(r'^[a-z_]\w*$', first) and first not in ('true', 'false'):
                return ManyN(Var(first), parse_inline(tokens[1]))
        return ManyN(None, parse_inline(rest))
    if content.startswith('Chunk '):
        rest = content[6:].strip()
        tokens = rest.split(None, 1)
        return ChunkN(parse_sexpr(tokens[0]), parse_inline(tokens[1]))
    if content == 'END':
        return End()
    if content in ('UInt8', 'BEUInt16', 'BEUInt32', 'LEUInt16', 'LEUInt32'):
        return Prim(content)
    if re.match(r'^[A-Z]\w*$', content):
        return Call(content)
    if content.startswith('Fail '):
        return End()
    if content.startswith('^'):
        return parse_sexpr(content[1:].strip())
    return parse_sexpr(content)


def parse_sexpr(s):
    s = s.strip()
    if not s:
        raise Exception("empty expr")
    for op in ('==', '!=', '<=', '>=', '<', '>'):
        depth = 0
        for i in range(len(s)):
            c = s[i]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif depth == 0 and s[i:i+len(op)] == op:
                if op in ('<', '>') and i + 1 < len(s) and s[i+1] == '=':
                    continue
                return BinOp(op, parse_sexpr(s[:i]), parse_sexpr(s[i+len(op):]))
    depth = 0
    for i in range(len(s) - 1, 0, -1):
        c = s[i]
        if c == ')':
            depth += 1
        elif c == '(':
            depth -= 1
        elif depth == 0 and c in '+-':
            return BinOp(c, parse_sexpr(s[:i]), parse_sexpr(s[i+1:]))
    depth = 0
    for i in range(len(s) - 1, 0, -1):
        c = s[i]
        if c == ')':
            depth += 1
        elif c == '(':
            depth -= 1
        elif depth == 0 and c in '*/':
            return BinOp(c, parse_sexpr(s[:i]), parse_sexpr(s[i+1:]))
    if s.startswith('(') and s.endswith(')'):
        return parse_sexpr(s[1:-1])
    if '.' in s and not s.startswith(('0x', '0X')):
        parts = s.split('.', 1)
        if parts[0].isidentifier() and parts[1].isidentifier():
            return FAcc(Var(parts[0]), parts[1])
    if s.startswith(('0x', '0X')):
        return Lit(int(s, 16))
    if s.isdigit():
        return Lit(int(s))
    if s == 'true':
        return Lit(1)
    if s == 'false':
        return Lit(0)
    if re.match(r'^[a-z_]\w*$', s):
        return Var(s)
    raise Exception(f"Cannot parse: {s!r}")


# ======================================================================
# C Code Generator
# ======================================================================

PRIM_MAP = {
    'UInt8':     ('uint8_t',  'ps_read_u8'),
    'BEUInt16':  ('uint16_t', 'ps_read_be16'),
    'BEUInt32':  ('uint32_t', 'ps_read_be32'),
    'LEUInt16':  ('uint16_t', 'ps_read_le16'),
    'LEUInt32':  ('uint32_t', 'ps_read_le32'),
}


class CGen:
    def __init__(self, defs):
        self.defs = defs
        self.out = []
        self.ind = 0
        self.uid = 0

    def fresh(self, pfx="t"):
        n = self.uid; self.uid += 1
        return f"_{pfx}{n}"

    def w(self, line=""):
        self.out.append("    " * self.ind + line)

    def generate(self):
        self.w('#include "parser.h"')
        self.w()
        for name in self.defs:
            self.w(f"jv_t *parse_{name}(pstate_t *ps);")
        self.w()
        for name, body in self.defs.items():
            self._gen_def(name, body)
        self._gen_main()
        return "\n".join(self.out) + "\n"

    # ------------------------------------------------------------------
    # Top-level def
    # ------------------------------------------------------------------

    def _gen_def(self, name, body):
        self.uid = 0
        self.w(f"jv_t *parse_{name}(pstate_t *ps) {{")
        self.ind += 1
        if isinstance(body, Block):
            self._gen_block(body, is_top=True)
        elif isinstance(body, FirstN):
            rv = self._gen_first(body)
            self.w(f"return {rv};")
            self.w("fail: return NULL;")
        elif isinstance(body, CaseN):
            rv = self._gen_case(body)
            self.w(f"return {rv};")
            self.w("fail: return NULL;")
        else:
            rv = self._gen_expr(body, "goto fail;")
            self.w(f"return {rv};")
            self.w("fail: return NULL;")
        self.ind -= 1
        self.w("}")
        self.w()

    # ------------------------------------------------------------------
    # Block (struct builder)
    # ------------------------------------------------------------------

    def _gen_block(self, block, is_top=False):
        has_fields = any(k == 'field' for k, _, _ in block.stmts)
        has_result = any(k == 'result' for k, _, _ in block.stmts)

        if has_fields:
            self.w("jv_t *obj = jv_object();")
        if has_result:
            self.w("jv_t *_eres = NULL;")

        for kind, name, node in block.stmts:
            if kind == 'field':
                self._gen_field(name, node, "obj")
            elif kind == 'let':
                self._gen_let(name, node, "goto fail;")
            elif kind == 'result':
                rv = self._gen_expr(node, "goto fail;")
                self.w(f"_eres = {rv};")
            elif kind == 'suppress':
                rv = self._gen_expr(node, "goto fail;")
                if rv:
                    self.w(f"jv_free({rv});")
            elif kind == 'exec':
                self._gen_exec(node, "goto fail;")

        if has_result:
            if has_fields:
                self.w("jv_free(obj);")
            self.w("return _eres;")
        elif has_fields:
            self.w("return obj;")
        else:
            self.w("return jv_null();")

        # fail label
        self.w("fail:")
        if has_result:
            self.w("    jv_free(_eres);")
        if has_fields:
            self.w("    jv_free(obj);")
        self.w("    return NULL;")

    # ------------------------------------------------------------------
    # Field: named output + local variable
    # ------------------------------------------------------------------

    def _gen_field(self, name, node, obj_var):
        """Emit code for a named field: parse, store on obj, and
        create a var_{name} int64_t local so it can be referenced later."""
        actual = node
        while isinstance(actual, Coerce):
            actual = actual.inner

        if isinstance(actual, Prim):
            ctype, func = PRIM_MAP[actual.name]
            tv = self.fresh("rd")
            self.w(f"{ctype} {tv};")
            self.w(f"if (!{func}(ps, &{tv})) goto fail;")
            self.w(f"int64_t var_{name} = (int64_t){tv}; (void)var_{name};")
            self.w(f'jv_set({obj_var}, "{name}", jv_int(var_{name}));')
        elif isinstance(actual, Call):
            rv = self.fresh("fc")
            self.w(f"jv_t *{rv} = parse_{actual.name}(ps);")
            self.w(f"if (!{rv}) goto fail;")
            self.w(f"int64_t var_{name} = jv_as_int({rv}); (void)var_{name};")
            self.w(f'jv_set({obj_var}, "{name}", {rv});')
        else:
            rv = self._gen_expr(node, "goto fail;")
            if rv:
                self.w(f"int64_t var_{name} = jv_as_int({rv}); (void)var_{name};")
                self.w(f'jv_set({obj_var}, "{name}", {rv});')
            else:
                self.w(f"int64_t var_{name} = 0; (void)var_{name};")
                self.w(f'jv_set({obj_var}, "{name}", jv_null());')

    # ------------------------------------------------------------------
    # Let binding (int64_t local only, no JSON output)
    # ------------------------------------------------------------------

    def _gen_let(self, name, node, on_fail):
        actual = node
        while isinstance(actual, Coerce):
            actual = actual.inner

        if isinstance(actual, Prim):
            ctype, func = PRIM_MAP[actual.name]
            tv = self.fresh("rd")
            self.w(f"{ctype} {tv};")
            self.w(f"if (!{func}(ps, &{tv})) {on_fail}")
            self.w(f"int64_t var_{name} = (int64_t){tv};")
        elif isinstance(actual, Call):
            jv = self.fresh("jl")
            self.w(f"jv_t *{jv} = parse_{actual.name}(ps);")
            self.w(f"if (!{jv}) {on_fail}")
            self.w(f"int64_t var_{name} = jv_as_int({jv});")
            self.w(f"jv_free({jv});")
        else:
            rv = self._gen_expr(actual, on_fail)
            if rv:
                self.w(f"int64_t var_{name} = jv_as_int({rv});")
                self.w(f"jv_free({rv});")
            else:
                self.w(f"int64_t var_{name} = 0;")

    # ------------------------------------------------------------------
    # Exec statement (side effects only)
    # ------------------------------------------------------------------

    def _gen_exec(self, node, on_fail):
        if isinstance(node, MatchB):
            mn = self.fresh("mb")
            vals = ", ".join(f"0x{v:02x}" for v in node.vals)
            self.w(f"{{ static const uint8_t {mn}[] = {{{vals}}};")
            self.w(f"  if (!ps_match(ps, {mn}, {len(node.vals)})) {on_fail} }}")
        elif isinstance(node, MatchS):
            mn = self.fresh("ms")
            vals = ", ".join(f"0x{b:02x}" for b in node.text.encode('ascii'))
            self.w(f"{{ static const uint8_t {mn}[] = {{{vals}}};")
            self.w(f"  if (!ps_match(ps, {mn}, {len(node.text)})) {on_fail} }}")
        elif isinstance(node, End):
            self.w(f"if (!ps_at_end(ps)) {on_fail}")
        elif isinstance(node, GuardN):
            cond = self._c_val(node.cond)
            self.w(f"if (!({cond})) {on_fail}")
        elif isinstance(node, Call):
            rv = self.fresh("ex")
            self.w(f"{{ jv_t *{rv} = parse_{node.name}(ps);")
            self.w(f"  if (!{rv}) {on_fail}")
            self.w(f"  jv_free({rv}); }}")
        else:
            rv = self._gen_expr(node, on_fail)
            if rv:
                self.w(f"jv_free({rv});")

    # ------------------------------------------------------------------
    # Parser expression → jv_t * (or None if no value produced)
    # ------------------------------------------------------------------

    def _gen_expr(self, node, on_fail):
        """Generate code producing a jv_t*.  Returns the C var name,
        or None for statements that produce no value (Match, END, Guard)."""

        if isinstance(node, Prim):
            ctype, func = PRIM_MAP[node.name]
            tv = self.fresh("rd")
            rv = self.fresh("pv")
            self.w(f"{ctype} {tv};")
            self.w(f"if (!{func}(ps, &{tv})) {on_fail}")
            self.w(f"jv_t *{rv} = jv_int((int64_t){tv});")
            return rv

        if isinstance(node, Coerce):
            return self._gen_expr(node.inner, on_fail)

        if isinstance(node, (MatchB, MatchS, End, GuardN)):
            self._gen_exec(node, on_fail)
            return None

        if isinstance(node, Call):
            rv = self.fresh("cv")
            self.w(f"jv_t *{rv} = parse_{node.name}(ps);")
            self.w(f"if (!{rv}) {on_fail}")
            return rv

        if isinstance(node, ManyN):
            return self._gen_many(node, on_fail)

        if isinstance(node, CaseN):
            return self._gen_case(node)

        if isinstance(node, Tagged):
            return self._gen_tagged(node, on_fail)

        if isinstance(node, FirstN):
            return self._gen_first(node)

        if isinstance(node, Choice):
            return self._gen_choice(node, on_fail)

        if isinstance(node, ChunkN):
            return self._gen_chunk(node, on_fail)

        if isinstance(node, Block):
            return self._gen_inline_block(node, on_fail)

        if isinstance(node, (Lit, Var, FAcc, BinOp)):
            rv = self.fresh("ev")
            val = self._c_val(node)
            self.w(f"jv_t *{rv} = jv_int((int64_t)({val}));")
            return rv

        raise Exception(f"Unhandled: {type(node).__name__}")

    # ------------------------------------------------------------------
    # Many (bounded and greedy)
    # ------------------------------------------------------------------

    def _gen_many(self, node, on_fail):
        rv = self.fresh("arr")
        self.w(f"jv_t *{rv} = jv_array();")

        if node.count is not None:
            # Bounded
            ce = self._c_val(node.count)
            iv = self.fresh("i")
            self.w(f"for (int64_t {iv} = 0; {iv} < (int64_t)({ce}); {iv}++) {{")
            self.ind += 1
            elem = self._gen_expr_guarded(node.parser, rv, on_fail)
            if elem:
                self.w(f"jv_push({rv}, {elem});")
            else:
                self.w(f"jv_push({rv}, jv_null());")
            self.ind -= 1
            self.w("}")
        else:
            # Greedy with backtracking
            self.w("for (;;) {")
            self.ind += 1
            sv = self.fresh("sv")
            self.w(f"size_t {sv} = ps_save(ps);")
            elem = self._gen_expr_try(node.parser)
            if elem:
                self.w(f"if (!{elem}) {{ ps_restore(ps, {sv}); break; }}")
                self.w(f"jv_push({rv}, {elem});")
            else:
                # Parser that doesn't return a value (e.g., Match)
                # succeeded if we get here, NULL if not — but this case
                # is unusual for Many body. Just break.
                self.w(f"ps_restore(ps, {sv}); break;")
            self.ind -= 1
            self.w("}")

        return rv

    def _gen_expr_guarded(self, node, arr_var, on_fail):
        """Like _gen_expr but on failure frees arr_var before on_fail."""
        fail_code = f"{{ jv_free({arr_var}); {on_fail} }}"

        actual = node
        while isinstance(actual, Coerce):
            actual = actual.inner

        if isinstance(actual, Prim):
            ctype, func = PRIM_MAP[actual.name]
            tv = self.fresh("rd")
            rv = self.fresh("ge")
            self.w(f"{ctype} {tv};")
            self.w(f"if (!{func}(ps, &{tv})) {fail_code}")
            self.w(f"jv_t *{rv} = jv_int((int64_t){tv});")
            return rv

        if isinstance(actual, Call):
            rv = self.fresh("gc")
            self.w(f"jv_t *{rv} = parse_{actual.name}(ps);")
            self.w(f"if (!{rv}) {fail_code}")
            return rv

        if isinstance(actual, Block):
            return self._gen_inline_block_guarded(actual, arr_var, on_fail)

        # Fallback
        return self._gen_expr(node, on_fail)

    def _gen_expr_try(self, node):
        """Generate parser that returns NULL on failure (no goto)."""
        actual = node
        while isinstance(actual, Coerce):
            actual = actual.inner

        if isinstance(actual, Prim):
            ctype, func = PRIM_MAP[actual.name]
            tv = self.fresh("rd")
            rv = self.fresh("te")
            self.w(f"jv_t *{rv} = NULL;")
            self.w(f"{{ {ctype} {tv};")
            self.w(f"  if ({func}(ps, &{tv})) {rv} = jv_int((int64_t){tv}); }}")
            return rv

        if isinstance(actual, Call):
            rv = self.fresh("tc")
            self.w(f"jv_t *{rv} = parse_{actual.name}(ps);")
            return rv

        if isinstance(actual, Block):
            return self._gen_inline_block_try(actual)

        if isinstance(actual, (MatchB, MatchS)):
            # Try to match, return null-sentinel on failure
            rv = self.fresh("tm")
            self.w(f"jv_t *{rv} = NULL;")
            if isinstance(actual, MatchB):
                mn = self.fresh("mb")
                vals = ", ".join(f"0x{v:02x}" for v in actual.vals)
                self.w(f"{{ static const uint8_t {mn}[] = {{{vals}}};")
                self.w(f"  if (ps_match(ps, {mn}, {len(actual.vals)})) {rv} = jv_null(); }}")
            else:
                mn = self.fresh("ms")
                vals = ", ".join(f"0x{b:02x}" for b in actual.text.encode('ascii'))
                self.w(f"{{ static const uint8_t {mn}[] = {{{vals}}};")
                self.w(f"  if (ps_match(ps, {mn}, {len(actual.text)})) {rv} = jv_null(); }}")
            return rv

        # Fallback: use goto fail (risky in try context but handled)
        return self._gen_expr(node, "goto fail;")

    # ------------------------------------------------------------------
    # Case
    # ------------------------------------------------------------------

    def _gen_case(self, node):
        rv = self.fresh("cr")
        disc = self._c_val(node.expr)
        self.w(f"jv_t *{rv} = NULL;")
        self.w(f"switch ((int64_t)({disc})) {{")
        has_default = False
        for pat, body in node.branches:
            if pat == '_':
                self.w("default: {")
                has_default = True
            else:
                self.w(f"case {pat}: {{")
            self.ind += 1
            val = self._gen_expr(body, "goto fail;")
            if val:
                self.w(f"{rv} = {val};")
            else:
                self.w(f"{rv} = jv_null();")
            self.w("break; }")
            self.ind -= 1
        if not has_default:
            self.w("default: goto fail;")
        self.w("}")
        return rv

    # ------------------------------------------------------------------
    # Tagged value {| tag = parser |}
    # ------------------------------------------------------------------

    def _gen_tagged(self, node, on_fail):
        inner = self._gen_expr(node.val, on_fail)
        rv = self.fresh("tg")
        self.w(f"jv_t *{rv} = jv_object();")
        if inner:
            self.w(f'jv_set({rv}, "{node.tag}", {inner});')
        else:
            self.w(f'jv_set({rv}, "{node.tag}", jv_null());')
        return rv

    # ------------------------------------------------------------------
    # First (tagged union with backtracking)
    # ------------------------------------------------------------------

    def _gen_first(self, node):
        rv = self.fresh("fr")
        self.w(f"jv_t *{rv} = NULL;")
        for tag, parser in node.alts:
            sv = self.fresh("fs")
            self.w(f"if (!{rv}) {{")
            self.ind += 1
            self.w(f"size_t {sv} = ps_save(ps);")
            inner = self._gen_expr_try(parser)
            if inner:
                self.w(f"if ({inner}) {{")
                self.ind += 1
                self.w(f"{rv} = jv_object();")
                self.w(f'jv_set({rv}, "{tag}", {inner});')
                self.ind -= 1
                self.w("} else {")
                self.ind += 1
                self.w(f"ps_restore(ps, {sv});")
                self.ind -= 1
                self.w("}")
            else:
                self.w(f"{rv} = jv_object();")
                self.w(f'jv_set({rv}, "{tag}", jv_null());')
            self.ind -= 1
            self.w("}")
        self.w(f"if (!{rv}) goto fail;")
        return rv

    # ------------------------------------------------------------------
    # Biased choice P <| Q
    # ------------------------------------------------------------------

    def _gen_choice(self, node, on_fail):
        rv = self.fresh("ch")
        sv = self.fresh("cs")
        self.w(f"jv_t *{rv} = NULL;")
        self.w(f"size_t {sv} = ps_save(ps);")
        left = self._gen_expr_try(node.left)
        if left:
            self.w(f"if ({left}) {{")
            self.ind += 1
            self.w(f"{rv} = {left};")
            self.ind -= 1
            self.w("} else {")
            self.ind += 1
            self.w(f"ps_restore(ps, {sv});")
            right = self._gen_expr(node.right, on_fail)
            self.w(f"{rv} = {right};" if right else f"{rv} = jv_null();")
            self.ind -= 1
            self.w("}")
        else:
            self.w(f"ps_restore(ps, {sv});")
            right = self._gen_expr(node.right, on_fail)
            self.w(f"{rv} = {right};" if right else f"{rv} = jv_null();")
        return rv

    # ------------------------------------------------------------------
    # Chunk (sub-stream)
    # ------------------------------------------------------------------

    def _gen_chunk(self, node, on_fail):
        size_expr = self._c_val(node.size)
        sv = self.fresh("sub")
        op = self.fresh("ops")
        self.w(f"pstate_t {sv};")
        self.w(f"if (!ps_chunk(ps, (size_t)({size_expr}), &{sv})) {on_fail}")
        self.w(f"pstate_t *{op} = ps;")
        self.w(f"ps = &{sv};")
        inner = self._gen_expr(node.parser, on_fail)
        self.w(f"ps = {op};")
        return inner

    # ------------------------------------------------------------------
    # Inline block (not top-level def)
    # ------------------------------------------------------------------

    def _gen_inline_block(self, block, on_fail):
        has_fields = any(k == 'field' for k, _, _ in block.stmts)
        has_result = any(k == 'result' for k, _, _ in block.stmts)

        if has_fields:
            rv = self.fresh("blk")
            self.w(f"jv_t *{rv} = jv_object();")
        elif has_result:
            rv = self.fresh("ber")
            self.w(f"jv_t *{rv} = NULL;")
        else:
            rv = self.fresh("bv")
            self.w(f"jv_t *{rv} = jv_null();")

        for kind, name, node in block.stmts:
            if kind == 'field':
                self._gen_field(name, node, rv)
            elif kind == 'let':
                self._gen_let(name, node, on_fail)
            elif kind == 'result':
                val = self._gen_expr(node, on_fail)
                self.w(f"{rv} = {val};" if val else f"{rv} = jv_null();")
            elif kind == 'suppress':
                val = self._gen_expr(node, on_fail)
                if val:
                    self.w(f"jv_free({val});")
            elif kind == 'exec':
                self._gen_exec(node, on_fail)

        return rv

    def _gen_inline_block_guarded(self, block, arr_var, on_fail):
        """Inline block inside a bounded Many: free arr on failure."""
        fail_code = f"{{ jv_free({arr_var}); {on_fail} }}"
        return self._gen_inline_block(block, fail_code)

    def _gen_inline_block_try(self, block):
        """Inline block that returns NULL on failure (for First/greedy Many)."""
        has_fields = any(k == 'field' for k, _, _ in block.stmts)
        has_result = any(k == 'result' for k, _, _ in block.stmts)

        rv = self.fresh("bt")
        ok = self.fresh("ok")
        if has_fields:
            self.w(f"jv_t *{rv} = jv_object();")
        elif has_result:
            self.w(f"jv_t *{rv} = NULL;")
        else:
            self.w(f"jv_t *{rv} = jv_null();")
        self.w(f"int {ok} = 1;")
        self.w("do {")
        self.ind += 1

        for kind, name, node in block.stmts:
            if kind == 'field':
                actual = node
                while isinstance(actual, Coerce):
                    actual = actual.inner
                if isinstance(actual, Prim):
                    ctype, func = PRIM_MAP[actual.name]
                    tv = self.fresh("rd")
                    self.w(f"{ctype} {tv};")
                    self.w(f"if (!{func}(ps, &{tv})) {{ {ok} = 0; break; }}")
                    self.w(f"int64_t var_{name} = (int64_t){tv}; (void)var_{name};")
                    self.w(f'jv_set({rv}, "{name}", jv_int(var_{name}));')
                elif isinstance(actual, Call):
                    cv = self.fresh("cv")
                    self.w(f"jv_t *{cv} = parse_{actual.name}(ps);")
                    self.w(f"if (!{cv}) {{ {ok} = 0; break; }}")
                    self.w(f"int64_t var_{name} = jv_as_int({cv}); (void)var_{name};")
                    self.w(f'jv_set({rv}, "{name}", {cv});')
                else:
                    val = self._gen_expr(node, f"{{ {ok} = 0; break; }}")
                    if val:
                        self.w(f"int64_t var_{name} = jv_as_int({val}); (void)var_{name};")
                        self.w(f'jv_set({rv}, "{name}", {val});')
                    else:
                        self.w(f"int64_t var_{name} = 0; (void)var_{name};")
                        self.w(f'jv_set({rv}, "{name}", jv_null());')
            elif kind == 'let':
                self._gen_let(name, node, f"{{ {ok} = 0; break; }}")
            elif kind == 'result':
                val = self._gen_expr(node, f"{{ {ok} = 0; break; }}")
                self.w(f"{rv} = {val};" if val else f"{rv} = jv_null();")
            elif kind == 'exec':
                if isinstance(node, MatchB):
                    mn = self.fresh("mb")
                    vals = ", ".join(f"0x{v:02x}" for v in node.vals)
                    self.w(f"{{ static const uint8_t {mn}[] = {{{vals}}};")
                    self.w(f"  if (!ps_match(ps, {mn}, {len(node.vals)})) {{ {ok} = 0; break; }} }}")
                elif isinstance(node, MatchS):
                    mn = self.fresh("ms")
                    vals = ", ".join(f"0x{b:02x}" for b in node.text.encode('ascii'))
                    self.w(f"{{ static const uint8_t {mn}[] = {{{vals}}};")
                    self.w(f"  if (!ps_match(ps, {mn}, {len(node.text)})) {{ {ok} = 0; break; }} }}")
                elif isinstance(node, End):
                    self.w(f"if (!ps_at_end(ps)) {{ {ok} = 0; break; }}")
                elif isinstance(node, GuardN):
                    cond = self._c_val(node.cond)
                    self.w(f"if (!({cond})) {{ {ok} = 0; break; }}")
                else:
                    self._gen_exec(node, f"{{ {ok} = 0; break; }}")
            elif kind == 'suppress':
                val = self._gen_expr(node, f"{{ {ok} = 0; break; }}")
                if val:
                    self.w(f"jv_free({val});")

        self.ind -= 1
        self.w("} while (0);")
        self.w(f"if (!{ok}) {{ jv_free({rv}); {rv} = NULL; }}")
        return rv

    # ------------------------------------------------------------------
    # C value expression (no jv_t, just raw int64_t computation)
    # ------------------------------------------------------------------

    def _c_val(self, node):
        if isinstance(node, Lit):
            return f"{node.v}LL"
        if isinstance(node, Var):
            return f"var_{node.name}"
        if isinstance(node, FAcc):
            return self._c_val(node.obj)
        if isinstance(node, BinOp):
            l = self._c_val(node.l)
            r = self._c_val(node.r)
            return f"(({l}) {node.op} ({r}))"
        raise Exception(f"Cannot gen C val for {type(node).__name__}")

    # ------------------------------------------------------------------
    # main()
    # ------------------------------------------------------------------

    def _gen_main(self):
        self.w("int main(int argc, char *argv[]) {")
        self.ind += 1
        self.w('if (argc != 2) { fprintf(stderr, "Usage: %s <input>\\n", argv[0]); return 1; }')
        self.w("size_t flen;")
        self.w("uint8_t *fdata = read_file(argv[1], &flen);")
        self.w('if (!fdata) { fprintf(stderr, "Cannot read %s\\n", argv[1]); return 1; }')
        self.w("pstate_t _ps;")
        self.w("ps_init(&_ps, fdata, flen);")
        self.w("pstate_t *ps = &_ps;")
        self.w("jv_t *result = parse_Main(ps);")
        self.w('if (!result) { fprintf(stderr, "Parse error\\n"); free(fdata); return 1; }')
        self.w("jv_print(result, stdout);")
        self.w('fprintf(stdout, "\\n");')
        self.w("jv_free(result);")
        self.w("free(fdata);")
        self.w("return 0;")
        self.ind -= 1
        self.w("}")


# ======================================================================
# Main
# ======================================================================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.ddl> <output.c>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        src = f.read()

    defs = parse_defs(src)
    if 'Main' not in defs:
        print(f"Error: no 'Main' in {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)

    gen = CGen(defs)
    code = gen.generate()

    with open(sys.argv[2], 'w') as f:
        f.write(code)


if __name__ == '__main__':
    main()
