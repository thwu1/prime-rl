#!/usr/bin/env python3
"""
DaeDaLus DDL subset interpreter.
Usage: python3 ddl_interp.py <spec.ddl> <input.bin> [entry_point]

Parses a .ddl specification file and uses it to parse a binary input file,
outputting the result as JSON to stdout.
"""
import sys
import json
import re
import struct


class Fail(Exception):
    """Raised when binary parsing fails (triggers backtracking)."""
    pass


# ======================================================================
# AST Node Types
# ======================================================================

class N:
    """Base AST node."""
    pass


class Block(N):
    def __init__(self, stmts):
        # stmts: list of (kind, name, node)
        # kind is 'field', 'let', 'result', 'suppress', or 'exec'
        self.stmts = stmts


class Prim(N):
    def __init__(self, name):
        self.name = name  # UInt8, BEUInt16, BEUInt32, LEUInt16, LEUInt32


class MatchB(N):
    def __init__(self, vals):
        self.vals = vals  # list of int


class MatchS(N):
    def __init__(self, text):
        self.text = text  # ASCII string


class End(N):
    pass


class ManyN(N):
    def __init__(self, count, parser):
        self.count = count    # expression node or None (unbounded)
        self.parser = parser  # parser node


class CaseN(N):
    def __init__(self, expr, branches):
        self.expr = expr          # expression node
        self.branches = branches  # list of (pattern, body)


class Tagged(N):
    def __init__(self, tag, val):
        self.tag = tag  # string
        self.val = val  # parser node


class FirstN(N):
    def __init__(self, alts):
        self.alts = alts  # list of (tag_name, parser)


class Choice(N):
    def __init__(self, left, right):
        self.left = left
        self.right = right


class ChunkN(N):
    def __init__(self, size, parser):
        self.size = size      # expression node
        self.parser = parser  # parser node


class GuardN(N):
    def __init__(self, cond):
        self.cond = cond  # expression node


class Call(N):
    def __init__(self, name):
        self.name = name  # references a top-level def


class Coerce(N):
    def __init__(self, inner):
        self.inner = inner  # treated as identity


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
# Binary Input Stream
# ======================================================================

class Stream:
    def __init__(self, data, pos=0, end=None):
        self.data = data
        self.pos = pos
        self.end = end if end is not None else len(data)

    def read(self, n):
        if self.pos + n > self.end:
            raise Fail(f"need {n} bytes at offset {self.pos}, "
                       f"only {self.end - self.pos} available")
        val = self.data[self.pos:self.pos + n]
        self.pos += n
        return val

    def at_end(self):
        return self.pos >= self.end

    def save(self):
        return self.pos

    def restore(self, p):
        self.pos = p

    def sub(self, n):
        """Create a bounded sub-stream of exactly n bytes."""
        if self.pos + n > self.end:
            raise Fail(f"sub-stream needs {n} bytes at offset {self.pos}")
        child = Stream(self.data, self.pos, self.pos + n)
        self.pos += n
        return child


# ======================================================================
# DDL Source Parser
# ======================================================================

def strip_comments(src):
    """Remove -- line comments and {- -} block comments."""
    # Block comments (nestable)
    while '{-' in src:
        start = src.index('{-')
        depth, i = 1, start + 2
        while i < len(src) and depth > 0:
            if src[i:i + 2] == '{-':
                depth += 1; i += 2
            elif src[i:i + 2] == '-}':
                depth -= 1; i += 2
            else:
                i += 1
        src = src[:start] + src[i:]
    # Line comments
    out = []
    for line in src.split('\n'):
        p = line.find('--')
        out.append(line[:p] if p >= 0 else line)
    return '\n'.join(out)


def get_lines(src):
    """Return [(indent, content, lineno)] for non-blank lines."""
    result = []
    for i, line in enumerate(src.split('\n')):
        s = line.rstrip()
        c = s.lstrip()
        if c:
            result.append((len(s) - len(c), c, i + 1))
    return result


def gather(lines, start, min_indent):
    """Collect consecutive lines with indent strictly greater than min_indent."""
    body, i = [], start
    while i < len(lines) and lines[i][0] > min_indent:
        body.append(lines[i])
        i += 1
    return body, i


def parse_defs(src):
    """Parse all top-level 'def Name = body' declarations."""
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
    """Parse a body (list of indented lines) into an AST node."""
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
    """Parse indented block statements."""
    if not lines:
        return Block([])
    bi = lines[0][0]  # block indent level
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
    """Find position of assignment '=' (not ==, <=, >=, !=).
    Returns None if no assignment found."""
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
            # Skip ==
            if i + 1 < len(s) and s[i + 1] == '=':
                i += 2
                continue
            # Skip <=, >=, !=
            if i > 0 and s[i - 1] in '<!>':
                i += 1
                continue
            pre = s[:i].strip()
            # Don't match = inside parser invocations
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
    """Parse a single block statement into (kind, name, node)."""
    # let binding
    if content.startswith('let ') and '=' in content:
        m = re.match(r'let\s+(\w+)\s*=\s*(.*)', content)
        return ('let', m.group(1),
                parse_inline(m.group(2).strip(), sub_lines, indent))

    # explicit result $$
    if content.startswith('$$'):
        r = re.match(r'\$\$\s*=\s*(.*)', content)
        return ('result', None,
                parse_inline(r.group(1).strip(), sub_lines, indent))

    # suppress @
    if content.startswith('@'):
        return ('suppress', None,
                parse_inline(content[1:].strip(), sub_lines, indent))

    # field = parser
    eq = find_eq(content)
    if eq is not None:
        name = content[:eq].strip()
        expr = content[eq + 1:].strip()
        return ('field', name, parse_inline(expr, sub_lines, indent))

    # bare execution (Match, END, Guard, parser call, etc.)
    return ('exec', None, parse_inline(content, sub_lines, indent))


def parse_first(lines):
    """Parse First alternatives."""
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
    """Parse case expr of ... with indented branches."""
    m = re.match(r'case\s+(.+?)\s+of\s*$', lines[0][1])
    if not m:
        raise Exception(f"Bad case syntax: {lines[0][1]}")
    expr = parse_sexpr(m.group(1).strip())
    cl = lines[1:]
    if not cl:
        raise Exception("empty case body")
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
    """Parse an inline parser expression (single line + continuations)."""
    if not extra:
        extra = []
    if not content:
        if extra:
            return parse_node(extra)
        raise Exception("empty inline expression")

    # Biased choice
    if ' <| ' in content:
        parts = content.split(' <| ', 1)
        return Choice(parse_inline(parts[0].strip()),
                      parse_inline(parts[1].strip(), extra, indent))

    # Type coercion: ... as[?!] uint N  or  ... as[?!] int
    cm = re.match(r'^(.+?)\s+as[?!]?\s+uint\s+\d+$', content)
    if cm:
        return Coerce(parse_inline(cm.group(1).strip()))
    cm2 = re.match(r'^(.+?)\s+as[?!]?\s+int$', content)
    if cm2:
        return Coerce(parse_inline(cm2.group(1).strip()))

    # block
    if content == 'block':
        return parse_block(extra)

    # First
    if content == 'First':
        return parse_first(extra)

    # case ... of
    if content.startswith('case '):
        return parse_case([(indent, content, 0)] + extra)

    # Tagged value {| tag = parser |}
    tm = re.match(r'^\{\|\s*(\w+)\s*=\s*(.*?)\s*\|\}$', content)
    if tm:
        return Tagged(tm.group(1), parse_inline(tm.group(2).strip()))

    # Match [bytes] or Match "string"
    if content.startswith('Match '):
        rest = content[6:].strip()
        if rest.startswith('['):
            bs = rest[1:rest.rindex(']')]
            vals = []
            for b in bs.split(','):
                b = b.strip()
                if not b:
                    continue
                if b.startswith('0x') or b.startswith('0X'):
                    vals.append(int(b, 16))
                else:
                    vals.append(int(b))
            return MatchB(vals)
        if rest.startswith('"'):
            return MatchS(rest[1:rest.rindex('"')])

    # Guard
    if content.startswith('Guard '):
        rest = content[6:].strip()
        if rest.startswith('(') and rest.endswith(')'):
            rest = rest[1:-1]
        return GuardN(parse_sexpr(rest))

    # Many [count] parser
    if content.startswith('Many '):
        rest = content[5:].strip()
        tokens = rest.split(None, 1)
        if len(tokens) >= 2:
            first = tokens[0]
            # Numeric count
            if re.match(r'^(\d+|0x[\da-fA-F]+)$', first):
                n = int(first, 16) if first.startswith('0x') else int(first)
                return ManyN(Lit(n), parse_inline(tokens[1]))
            # Variable count (lowercase identifier)
            if (re.match(r'^[a-z_]\w*$', first)
                    and first not in ('true', 'false')):
                return ManyN(Var(first), parse_inline(tokens[1]))
        return ManyN(None, parse_inline(rest))

    # Chunk size parser
    if content.startswith('Chunk '):
        rest = content[6:].strip()
        tokens = rest.split(None, 1)
        return ChunkN(parse_sexpr(tokens[0]), parse_inline(tokens[1]))

    # END
    if content == 'END':
        return End()

    # Primitive parsers
    if content in ('UInt8', 'BEUInt16', 'BEUInt32', 'LEUInt16', 'LEUInt32'):
        return Prim(content)

    # User-defined parser call (uppercase identifier)
    if re.match(r'^[A-Z]\w*$', content):
        return Call(content)

    # Fail
    if content.startswith('Fail '):
        return End()  # treat Fail as unconditional failure

    # Pure value ^expr
    if content.startswith('^'):
        return parse_sexpr(content[1:].strip())

    # Fall back to expression
    return parse_sexpr(content)


def parse_sexpr(s):
    """Parse a simple expression (comparisons, arithmetic, literals, vars)."""
    s = s.strip()
    if not s:
        raise Exception("empty expression")

    # Comparison operators (lowest precedence)
    for op in ('==', '!=', '<=', '>=', '<', '>'):
        depth = 0
        for i in range(len(s)):
            c = s[i]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif depth == 0 and s[i:i + len(op)] == op:
                # Don't match < when it's actually <=
                if op in ('<', '>') and i + 1 < len(s) and s[i + 1] == '=':
                    continue
                return BinOp(op,
                             parse_sexpr(s[:i]),
                             parse_sexpr(s[i + len(op):]))

    # Addition/subtraction (right-to-left scan for left-assoc)
    depth = 0
    for i in range(len(s) - 1, 0, -1):
        c = s[i]
        if c == ')':
            depth += 1
        elif c == '(':
            depth -= 1
        elif depth == 0 and c in '+-':
            return BinOp(c, parse_sexpr(s[:i]), parse_sexpr(s[i + 1:]))

    # Multiplication/division
    depth = 0
    for i in range(len(s) - 1, 0, -1):
        c = s[i]
        if c == ')':
            depth += 1
        elif c == '(':
            depth -= 1
        elif depth == 0 and c in '*/':
            return BinOp(c, parse_sexpr(s[:i]), parse_sexpr(s[i + 1:]))

    # Parenthesized expression
    if s.startswith('(') and s.endswith(')'):
        return parse_sexpr(s[1:-1])

    # Field access: var.field
    if '.' in s and not s.startswith('0x') and not s.startswith('0X'):
        parts = s.split('.', 1)
        if parts[0].isidentifier() and parts[1].isidentifier():
            return FAcc(Var(parts[0]), parts[1])

    # Hex literal
    if s.startswith('0x') or s.startswith('0X'):
        return Lit(int(s, 16))

    # Decimal literal
    if s.isdigit():
        return Lit(int(s))

    # Boolean
    if s == 'true':
        return Lit(1)
    if s == 'false':
        return Lit(0)

    # Variable
    if re.match(r'^[a-z_]\w*$', s):
        return Var(s)

    raise Exception(f"Cannot parse expression: {s!r}")


# ======================================================================
# Interpreter
# ======================================================================

def interp(node, stream, env, defs):
    """Interpret an AST node, consuming bytes from stream."""

    if isinstance(node, Block):
        result = {}
        has_explicit = False
        explicit_val = None
        local_env = dict(env)
        for kind, name, sub in node.stmts:
            val = interp(sub, stream, local_env, defs)
            if kind == 'field':
                result[name] = val
                local_env[name] = val
            elif kind == 'let':
                local_env[name] = val
            elif kind == 'result':
                has_explicit = True
                explicit_val = val
                local_env['$$'] = val
            # suppress and exec: side effects only
        return explicit_val if has_explicit else result

    if isinstance(node, Prim):
        name = node.name
        if name == 'UInt8':
            return stream.read(1)[0]
        if name == 'BEUInt16':
            return struct.unpack('>H', stream.read(2))[0]
        if name == 'BEUInt32':
            return struct.unpack('>I', stream.read(4))[0]
        if name == 'LEUInt16':
            return struct.unpack('<H', stream.read(2))[0]
        if name == 'LEUInt32':
            return struct.unpack('<I', stream.read(4))[0]
        raise Fail(f"Unknown primitive: {name}")

    if isinstance(node, MatchB):
        data = stream.read(len(node.vals))
        for i, v in enumerate(node.vals):
            if data[i] != v:
                raise Fail(f"Match byte failed at position {i}: "
                           f"expected 0x{v:02x}, got 0x{data[i]:02x}")
        return None

    if isinstance(node, MatchS):
        expected = node.text.encode('ascii')
        data = stream.read(len(expected))
        if data != expected:
            raise Fail(f"Match string failed: expected {node.text!r}")
        return None

    if isinstance(node, End):
        if not stream.at_end():
            raise Fail(f"END failed: {stream.end - stream.pos} bytes remaining")
        return None

    if isinstance(node, ManyN):
        if node.count is not None:
            # Bounded: parse exactly N times
            n = eval_expr(node.count, env)
            results = []
            for _ in range(n):
                results.append(interp(node.parser, stream, env, defs))
            return results
        else:
            # Unbounded: parse until failure, with backtracking
            results = []
            while True:
                pos = stream.save()
                try:
                    results.append(interp(node.parser, stream, env, defs))
                except Fail:
                    stream.restore(pos)
                    break
            return results

    if isinstance(node, CaseN):
        val = eval_expr(node.expr, env)
        for pat, body in node.branches:
            if pat == '_' or pat == val:
                return interp(body, stream, env, defs)
        raise Fail(f"No case branch matched value {val}")

    if isinstance(node, Tagged):
        val = interp(node.val, stream, env, defs)
        return {node.tag: val}

    if isinstance(node, FirstN):
        for tag, parser in node.alts:
            pos = stream.save()
            try:
                val = interp(parser, stream, env, defs)
                return {tag: val}
            except Fail:
                stream.restore(pos)
        raise Fail("All First alternatives failed")

    if isinstance(node, Choice):
        pos = stream.save()
        try:
            return interp(node.left, stream, env, defs)
        except Fail:
            stream.restore(pos)
            return interp(node.right, stream, env, defs)

    if isinstance(node, ChunkN):
        size = eval_expr(node.size, env)
        sub_stream = stream.sub(size)
        return interp(node.parser, sub_stream, env, defs)

    if isinstance(node, GuardN):
        val = eval_expr(node.cond, env)
        if not val:
            raise Fail("Guard condition failed")
        return None

    if isinstance(node, Call):
        if node.name not in defs:
            raise Fail(f"Unknown definition: {node.name}")
        return interp(defs[node.name], stream, env, defs)

    if isinstance(node, Coerce):
        return interp(node.inner, stream, env, defs)

    # Expression node (Lit, Var, etc.) — evaluate without consuming input
    return eval_expr(node, env)


def eval_expr(node, env):
    """Evaluate an expression node to a Python value."""
    if isinstance(node, Lit):
        return node.v
    if isinstance(node, Var):
        if node.name in env:
            return env[node.name]
        raise Fail(f"Unbound variable: {node.name}")
    if isinstance(node, FAcc):
        obj = eval_expr(node.obj, env)
        if isinstance(obj, dict) and node.field in obj:
            return obj[node.field]
        raise Fail(f"Field access failed: .{node.field}")
    if isinstance(node, BinOp):
        l = eval_expr(node.l, env)
        r = eval_expr(node.r, env)
        ops = {
            '+': lambda: l + r,
            '-': lambda: l - r,
            '*': lambda: l * r,
            '/': lambda: l // r,
            '==': lambda: l == r,
            '!=': lambda: l != r,
            '<': lambda: l < r,
            '<=': lambda: l <= r,
            '>': lambda: l > r,
            '>=': lambda: l >= r,
        }
        if node.op in ops:
            return ops[node.op]()
        raise Fail(f"Unknown operator: {node.op}")
    raise Fail(f"Cannot evaluate node type: {type(node).__name__}")


# ======================================================================
# Main Entry Point
# ======================================================================

def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <spec.ddl> <input.bin> [entry]",
              file=sys.stderr)
        sys.exit(1)

    ddl_file = sys.argv[1]
    bin_file = sys.argv[2]
    entry = sys.argv[3] if len(sys.argv) > 3 else 'Main'

    with open(ddl_file) as f:
        ddl_src = f.read()
    with open(bin_file, 'rb') as f:
        bin_data = f.read()

    defs = parse_defs(ddl_src)
    if entry not in defs:
        print(f"Error: entry point '{entry}' not found in {ddl_file}",
              file=sys.stderr)
        sys.exit(1)

    stream = Stream(bin_data)
    try:
        result = interp(defs[entry], stream, {}, defs)
        print(json.dumps(result))
    except Fail as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
