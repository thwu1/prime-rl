"""
CQL (Clinical Quality Language) Expression Evaluator
Implements tokenizer, recursive descent parser, and tree-walking evaluator
for a substantial subset of CQL 1.5.

"""

import re
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, InvalidOperation

# ═══════════════════════════════════════════════════════════════════════
# CQL TYPE SYSTEM
# ═══════════════════════════════════════════════════════════════════════

class CqlNull:
    _inst = None
    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst
    def __repr__(self): return 'null'
    def __bool__(self): return False
    def __eq__(self, o): return isinstance(o, CqlNull)
    def __hash__(self): return 0

NULL = CqlNull()
def is_null(v): return isinstance(v, CqlNull)

class CqlLong:
    __slots__ = ('value',)
    def __init__(self, v): self.value = int(v)
    def __eq__(self, o): return isinstance(o, CqlLong) and self.value == o.value
    def __hash__(self): return hash(('L', self.value))
    def __repr__(self): return f'{self.value}L'

class CqlDateTime:
    __slots__ = ('year','month','day','hour','minute','second','millisecond','tz')
    def __init__(self, year=None, month=None, day=None, hour=None,
                 minute=None, second=None, millisecond=None, tz=None):
        self.year=year; self.month=month; self.day=day; self.hour=hour
        self.minute=minute; self.second=second; self.millisecond=millisecond; self.tz=tz
    def __eq__(self, o):
        if not isinstance(o, CqlDateTime): return NotImplemented
        return (self.year==o.year and self.month==o.month and self.day==o.day
                and self.hour==o.hour and self.minute==o.minute
                and self.second==o.second and self.millisecond==o.millisecond)
    def __hash__(self):
        return hash(('DT', self.year, self.month, self.day,
                      self.hour, self.minute, self.second, self.millisecond))
    def __lt__(self, o):
        if not isinstance(o, CqlDateTime): return NotImplemented
        return self._cmp_tuple() < o._cmp_tuple()
    def __le__(self, o):
        if not isinstance(o, CqlDateTime): return NotImplemented
        return self._cmp_tuple() <= o._cmp_tuple()
    def __gt__(self, o):
        if not isinstance(o, CqlDateTime): return NotImplemented
        return self._cmp_tuple() > o._cmp_tuple()
    def __ge__(self, o):
        if not isinstance(o, CqlDateTime): return NotImplemented
        return self._cmp_tuple() >= o._cmp_tuple()
    def _cmp_tuple(self):
        return (self.year or 0, self.month or 0, self.day or 0,
                self.hour or 0, self.minute or 0, self.second or 0, self.millisecond or 0)

class CqlTime:
    __slots__ = ('hour','minute','second','millisecond')
    def __init__(self, hour=None, minute=None, second=None, millisecond=None):
        self.hour=hour; self.minute=minute; self.second=second; self.millisecond=millisecond
    def __eq__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return (self.hour==o.hour and self.minute==o.minute
                and self.second==o.second and self.millisecond==o.millisecond)
    def __hash__(self):
        return hash(('T', self.hour, self.minute, self.second, self.millisecond))
    def __lt__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._t() < o._t()
    def __le__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._t() <= o._t()
    def __gt__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._t() > o._t()
    def __ge__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._t() >= o._t()
    def _t(self):
        return (self.hour or 0, self.minute or 0, self.second or 0, self.millisecond or 0)

class CqlQuantity:
    __slots__ = ('value','unit')
    def __init__(self, value, unit):
        self.value = Decimal(str(value)) if not isinstance(value, Decimal) else value
        self.unit = unit
    def __eq__(self, o):
        if not isinstance(o, CqlQuantity): return NotImplemented
        return self.value == o.value and self.unit == o.unit
    def __hash__(self): return hash(('Q', self.value, self.unit))

class CqlInterval:
    __slots__ = ('low','high','low_closed','high_closed')
    def __init__(self, low, high, low_closed=True, high_closed=True):
        self.low=low; self.high=high
        self.low_closed=low_closed; self.high_closed=high_closed
    def __eq__(self, o):
        if not isinstance(o, CqlInterval): return NotImplemented
        return (self.low==o.low and self.high==o.high
                and self.low_closed==o.low_closed and self.high_closed==o.high_closed)

class CqlTuple:
    __slots__ = ('fields',)
    def __init__(self, fields): self.fields = dict(fields)
    def __eq__(self, o):
        if not isinstance(o, CqlTuple): return NotImplemented
        return self.fields == o.fields

# ═══════════════════════════════════════════════════════════════════════
# TOKENIZER
# ═══════════════════════════════════════════════════════════════════════

TK_INT='INT'; TK_DEC='DEC'; TK_LONG='LONG'; TK_STR='STR'
TK_DT='DT'; TK_TIME='TIME'; TK_KW='KW'; TK_ID='ID'; TK_OP='OP'
TK_LP='('; TK_RP=')'; TK_LB='{'; TK_RB='}'; TK_LS='['; TK_RS=']'
TK_COMMA=','; TK_COLON=':'; TK_DOT='.'; TK_EOF='EOF'

KEYWORDS = {
    'true','false','null','and','or','xor','not','implies',
    'if','then','else','case','when','end',
    'Interval','List','Tuple','as','is','in','contains',
    'includes','included','properly','between','div','mod',
    'distinct','flatten','singleton','from',
    'predecessor','successor','of','minimum','maximum',
    'union','intersect','except','sort','asc','desc',
    'Integer','Decimal','Long','String','Boolean','DateTime','Date','Time','Any',
    'Abs','Ceiling','Floor','Round','Truncate','Exp','Ln','Log','Power',
    'First','Last','Length','Exists','IndexOf','Flatten',
    'Combine','Concatenate','Skip','Take','Tail','Slice',
    'HighBoundary','LowBoundary','Precision',
}

class Tok:
    __slots__ = ('t','v','p')
    def __init__(self, t, v, p=0): self.t=t; self.v=v; self.p=p
    def __repr__(self): return f'Tok({self.t},{self.v!r})'

def tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in ' \t\r\n':
            i += 1; continue

        # DateTime/Time literal
        if c == '@':
            j = i + 1
            if j < n and src[j] == 'T':
                j += 1
                while j < n and (src[j].isdigit() or src[j] in ':.'):
                    j += 1
                toks.append(Tok(TK_TIME, src[i:j], i))
            else:
                while j < n and (src[j].isdigit() or src[j] in '-T:.Z+'):
                    j += 1
                toks.append(Tok(TK_DT, src[i:j], i))
            i = j; continue

        # String literal
        if c == "'":
            j = i + 1
            while j < n:
                if src[j] == '\\': j += 2
                elif src[j] == "'": j += 1; break
                else: j += 1
            toks.append(Tok(TK_STR, src[i:j], i))
            i = j; continue

        # Number
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit(): j += 1
            if j < n and src[j] == 'L':
                toks.append(Tok(TK_LONG, src[i:j+1], i)); i = j+1
            elif j < n and src[j] == '.' and j+1 < n and src[j+1].isdigit():
                j += 1
                while j < n and src[j].isdigit(): j += 1
                toks.append(Tok(TK_DEC, src[i:j], i)); i = j
            else:
                toks.append(Tok(TK_INT, src[i:j], i)); i = j
            continue

        # Two-char operators
        if i+1 < n and src[i:i+2] in ('!=','!~','<=','>='):
            toks.append(Tok(TK_OP, src[i:i+2], i)); i += 2; continue

        # Single-char operators
        if c in '+-*/^=<>~|&':
            toks.append(Tok(TK_OP, c, i)); i += 1; continue
        if c == '!':
            toks.append(Tok(TK_OP, '!', i)); i += 1; continue

        # Delimiters
        dm = {'(':TK_LP, ')':TK_RP, '{':TK_LB, '}':TK_RB,
              '[':TK_LS, ']':TK_RS, ',':TK_COMMA, ':':TK_COLON, '.':TK_DOT}
        if c in dm:
            toks.append(Tok(dm[c], c, i)); i += 1; continue

        # Identifiers / keywords
        if c.isalpha() or c == '_':
            j = i
            while j < n and (src[j].isalnum() or src[j] == '_'): j += 1
            w = src[i:j]
            toks.append(Tok(TK_KW if w in KEYWORDS else TK_ID, w, i))
            i = j; continue

        i += 1  # skip unknown

    toks.append(Tok(TK_EOF, None, n))
    return toks

# ═══════════════════════════════════════════════════════════════════════
# AST NODES
# ═══════════════════════════════════════════════════════════════════════

class Lit:
    def __init__(self, val): self.val = val
class BinOp:
    def __init__(self, op, l, r): self.op=op; self.l=l; self.r=r
class UnaryOp:
    def __init__(self, op, operand): self.op=op; self.operand=operand
class FnCall:
    def __init__(self, name, args): self.name=name; self.args=args
class IfExpr:
    def __init__(self, cond, then_, else_): self.cond=cond; self.then_=then_; self.else_=else_
class CaseExpr:
    def __init__(self, comparand, whens, else_):
        self.comparand=comparand; self.whens=whens; self.else_=else_
class ListExpr:
    def __init__(self, items): self.items=items
class IntervalExpr:
    def __init__(self, low, high, lc, hc): self.low=low; self.high=high; self.lc=lc; self.hc=hc
class IndexExpr:
    def __init__(self, base, idx): self.base=base; self.idx=idx
class PredSucc:
    def __init__(self, op, operand): self.op=op; self.operand=operand
class MinMax:
    def __init__(self, op, typ): self.op=op; self.typ=typ
class TypeTest:
    def __init__(self, operand, test): self.operand=operand; self.test=test
class TypeCast:
    def __init__(self, operand, typ): self.operand=operand; self.typ=typ
class BetweenExpr:
    def __init__(self, operand, low, high): self.operand=operand; self.low=low; self.high=high
class TupleExpr:
    def __init__(self, fields): self.fields = fields
class QuantityExpr:
    def __init__(self, value, unit): self.value=value; self.unit=unit
class MemberExpr:
    def __init__(self, obj, member): self.obj=obj; self.member=member

# ═══════════════════════════════════════════════════════════════════════
# PARSER
# ═══════════════════════════════════════════════════════════════════════

class Parser:
    def __init__(self, toks):
        self.toks = toks; self.pos = 0

    def peek(self): return self.toks[self.pos]
    def advance(self):
        t = self.toks[self.pos]; self.pos += 1; return t
    def at(self, typ, val=None):
        t = self.peek()
        if t.t != typ: return False
        if val is not None and t.v != val: return False
        return True
    def eat(self, typ, val=None):
        if self.at(typ, val): return self.advance()
        return None
    def expect(self, typ, val=None):
        t = self.eat(typ, val)
        if t is None:
            pk = self.peek()
            raise SyntaxError(f'Expected {typ}({val}) at pos {pk.p}, got {pk.t}({pk.v})')
        return t

    def parse(self):
        node = self.parse_implies()
        return node

    # ── Expression levels (lowest to highest precedence) ──

    def parse_implies(self):
        left = self.parse_or()
        while self.eat(TK_KW, 'implies'):
            left = BinOp('implies', left, self.parse_or())
        return left

    def parse_or(self):
        left = self.parse_and()
        while True:
            if self.eat(TK_KW, 'or'):
                left = BinOp('or', left, self.parse_and())
            elif self.eat(TK_KW, 'xor'):
                left = BinOp('xor', left, self.parse_and())
            else: break
        return left

    def parse_and(self):
        left = self.parse_membership()
        while self.eat(TK_KW, 'and'):
            left = BinOp('and', left, self.parse_membership())
        return left

    def parse_membership(self):
        left = self.parse_equality()
        while True:
            if self.eat(TK_KW, 'in'):
                left = BinOp('in', left, self.parse_equality())
            elif self.eat(TK_KW, 'contains'):
                left = BinOp('contains', left, self.parse_equality())
            elif self.at(TK_KW, 'includes'):
                self.advance()
                left = BinOp('includes', left, self.parse_equality())
            elif self.at(TK_KW, 'included'):
                self.advance()
                self.expect(TK_KW, 'in')
                left = BinOp('included in', left, self.parse_equality())
            elif self.at(TK_KW, 'properly'):
                saved = self.pos
                self.advance()
                if self.eat(TK_KW, 'includes'):
                    left = BinOp('properly includes', left, self.parse_equality())
                elif self.eat(TK_KW, 'included'):
                    self.expect(TK_KW, 'in')
                    left = BinOp('properly included in', left, self.parse_equality())
                else:
                    self.pos = saved; break
            else: break
        return left

    def parse_equality(self):
        left = self.parse_inequality()
        while True:
            if self.at(TK_OP, '='):
                self.advance(); left = BinOp('=', left, self.parse_inequality())
            elif self.at(TK_OP, '!='):
                self.advance(); left = BinOp('!=', left, self.parse_inequality())
            elif self.at(TK_OP, '~'):
                self.advance(); left = BinOp('~', left, self.parse_inequality())
            elif self.at(TK_OP, '!~'):
                self.advance(); left = BinOp('!~', left, self.parse_inequality())
            else: break
        return left

    def parse_inequality(self):
        left = self.parse_set_ops()
        while True:
            if self.at(TK_OP, '<'):
                self.advance(); left = BinOp('<', left, self.parse_set_ops())
            elif self.at(TK_OP, '>'):
                self.advance(); left = BinOp('>', left, self.parse_set_ops())
            elif self.at(TK_OP, '<='):
                self.advance(); left = BinOp('<=', left, self.parse_set_ops())
            elif self.at(TK_OP, '>='):
                self.advance(); left = BinOp('>=', left, self.parse_set_ops())
            else: break
        return left

    def parse_set_ops(self):
        left = self.parse_type_expr()
        while True:
            if self.eat(TK_KW, 'union') or self.eat(TK_OP, '|'):
                left = BinOp('union', left, self.parse_type_expr())
            elif self.eat(TK_KW, 'intersect'):
                left = BinOp('intersect', left, self.parse_type_expr())
            elif self.eat(TK_KW, 'except'):
                left = BinOp('except', left, self.parse_type_expr())
            else: break
        return left

    def parse_type_expr(self):
        left = self.parse_addition()
        # Handle 'is null', 'is not null', 'is true', 'is false', 'as Type'
        while True:
            if self.at(TK_KW, 'is'):
                self.advance()
                if self.eat(TK_KW, 'not'):
                    if self.eat(TK_KW, 'null'):
                        left = TypeTest(left, 'is not null')
                    else:
                        raise SyntaxError("Expected 'null' after 'is not'")
                elif self.eat(TK_KW, 'null'):
                    left = TypeTest(left, 'is null')
                elif self.eat(TK_KW, 'true'):
                    left = TypeTest(left, 'is true')
                elif self.eat(TK_KW, 'false'):
                    left = TypeTest(left, 'is false')
                else:
                    # is TypeSpecifier — just parse the type name
                    typ = self.expect(TK_KW).v
                    left = TypeTest(left, f'is {typ}')
            elif self.at(TK_KW, 'as'):
                self.advance()
                typ = self.parse_type_name()
                left = TypeCast(left, typ)
            elif self.at(TK_KW, 'between'):
                self.advance()
                low = self.parse_addition()
                self.expect(TK_KW, 'and')
                high = self.parse_addition()
                left = BetweenExpr(left, low, high)
            else: break
        return left

    def parse_type_name(self):
        """Parse a type name like Integer, List<Integer>, etc."""
        name = self.expect(TK_KW).v
        if self.eat(TK_OP, '<'):
            inner = self.parse_type_name()
            self.expect(TK_OP, '>')
            return f'{name}<{inner}>'
        return name

    # ── ExpressionTerm levels ──

    def parse_addition(self):
        left = self.parse_multiplication()
        while True:
            if self.at(TK_OP, '+'):
                self.advance(); left = BinOp('+', left, self.parse_multiplication())
            elif self.at(TK_OP, '-'):
                # Disambiguate: is '-' binary subtraction or start of negative literal?
                # If left is an expression node, treat as binary
                self.advance(); left = BinOp('-', left, self.parse_multiplication())
            elif self.at(TK_OP, '&'):
                self.advance(); left = BinOp('&', left, self.parse_multiplication())
            else: break
        return left

    def parse_multiplication(self):
        left = self.parse_power()
        while True:
            if self.at(TK_OP, '*'):
                self.advance(); left = BinOp('*', left, self.parse_power())
            elif self.at(TK_OP, '/'):
                self.advance(); left = BinOp('/', left, self.parse_power())
            elif self.eat(TK_KW, 'div'):
                left = BinOp('div', left, self.parse_power())
            elif self.eat(TK_KW, 'mod'):
                left = BinOp('mod', left, self.parse_power())
            else: break
        return left

    def parse_power(self):
        left = self.parse_unary()
        if self.at(TK_OP, '^'):
            self.advance()
            right = self.parse_unary()
            return BinOp('^', left, right)
        return left

    def parse_unary(self):
        if self.at(TK_OP, '-'):
            self.advance()
            operand = self.parse_unary()
            return UnaryOp('-', operand)
        if self.at(TK_OP, '+'):
            self.advance()
            return self.parse_unary()
        if self.eat(TK_KW, 'not'):
            return UnaryOp('not', self.parse_unary())
        if self.eat(TK_KW, 'exists'):
            return FnCall('Exists', [self.parse_unary()])
        if self.at(TK_KW, 'distinct'):
            self.advance()
            return FnCall('distinct', [self.parse_unary()])
        if self.at(TK_KW, 'flatten'):
            self.advance()
            return FnCall('flatten', [self.parse_unary()])
        # 'singleton from'
        if self.at(TK_KW, 'singleton'):
            self.advance()
            self.expect(TK_KW, 'from')
            return FnCall('singleton from', [self.parse_unary()])
        # 'predecessor of' / 'successor of'
        if self.at(TK_KW, 'predecessor'):
            self.advance(); self.expect(TK_KW, 'of')
            return PredSucc('predecessor', self.parse_unary())
        if self.at(TK_KW, 'successor'):
            self.advance(); self.expect(TK_KW, 'of')
            return PredSucc('successor', self.parse_unary())
        # 'minimum Type' / 'maximum Type'
        if self.at(TK_KW, 'minimum'):
            self.advance()
            typ = self.expect(TK_KW).v
            return MinMax('minimum', typ)
        if self.at(TK_KW, 'maximum'):
            self.advance()
            typ = self.expect(TK_KW).v
            return MinMax('maximum', typ)
        return self.parse_postfix()

    def parse_postfix(self):
        left = self.parse_primary()
        while True:
            if self.at(TK_LS):
                self.advance()
                idx = self.parse_implies()
                self.expect(TK_RS)
                left = IndexExpr(left, idx)
            elif self.at(TK_DOT):
                self.advance()
                member = self.peek().v
                self.advance()
                if self.at(TK_LP):
                    # method call
                    self.advance()
                    args = [left]
                    if not self.at(TK_RP):
                        args.append(self.parse_implies())
                        while self.eat(TK_COMMA):
                            args.append(self.parse_implies())
                    self.expect(TK_RP)
                    left = FnCall(member, args)
                else:
                    left = MemberExpr(left, member)
            else: break
        return left

    def parse_primary(self):
        tk = self.peek()

        # Literals
        if tk.t == TK_INT:
            self.advance(); return Lit(int(tk.v))
        if tk.t == TK_DEC:
            self.advance(); return Lit(Decimal(tk.v))
        if tk.t == TK_LONG:
            self.advance(); return Lit(CqlLong(int(tk.v[:-1])))
        if tk.t == TK_STR:
            self.advance(); return Lit(parse_cql_string(tk.v))
        if tk.t == TK_DT:
            self.advance(); return Lit(parse_datetime_literal(tk.v))
        if tk.t == TK_TIME:
            self.advance(); return Lit(parse_time_literal(tk.v))

        # Boolean / null
        if tk.t == TK_KW and tk.v == 'true':
            self.advance(); return Lit(True)
        if tk.t == TK_KW and tk.v == 'false':
            self.advance(); return Lit(False)
        if tk.t == TK_KW and tk.v == 'null':
            self.advance(); return Lit(NULL)

        # Parenthesized expression
        if tk.t == TK_LP:
            self.advance()
            expr = self.parse_implies()
            self.expect(TK_RP)
            return expr

        # List literal { ... }
        if tk.t == TK_LB:
            return self.parse_list()

        # if/then/else
        if tk.t == TK_KW and tk.v == 'if':
            return self.parse_if()

        # case
        if tk.t == TK_KW and tk.v == 'case':
            return self.parse_case()

        # Interval constructor
        if tk.t == TK_KW and tk.v == 'Interval':
            return self.parse_interval()

        # Tuple constructor
        if tk.t == TK_KW and tk.v == 'Tuple':
            self.advance()
            self.expect(TK_LB)
            fields = []
            if not self.at(TK_RB) and not self.at(TK_COLON):
                name = self.peek().v; self.advance()
                self.expect(TK_COLON)
                val = self.parse_implies()
                fields.append((name, val))
                while self.eat(TK_COMMA):
                    name = self.peek().v; self.advance()
                    self.expect(TK_COLON)
                    val = self.parse_implies()
                    fields.append((name, val))
            elif self.eat(TK_COLON):
                pass  # empty tuple {:}
            self.expect(TK_RB)
            return TupleExpr(fields)

        # Function calls (DateTime, Abs, etc.)
        if tk.t == TK_KW and tk.v in ('DateTime','Date','Time','Abs','Ceiling','Floor',
            'Round','Truncate','Exp','Ln','Log','Power','First','Last','Length',
            'Exists','IndexOf','Flatten','Combine','Concatenate','Skip','Take',
            'Tail','Slice','HighBoundary','LowBoundary','Precision'):
            name = tk.v; self.advance()
            self.expect(TK_LP)
            args = []
            if not self.at(TK_RP):
                args.append(self.parse_implies())
                while self.eat(TK_COMMA):
                    args.append(self.parse_implies())
            self.expect(TK_RP)
            return FnCall(name, args)

        # Identifier (fallback) — also handles identifiers used in query aliases etc.
        if tk.t in (TK_KW, TK_ID):
            self.advance()
            # Check for function call pattern
            if self.at(TK_LP):
                self.advance()
                args = []
                if not self.at(TK_RP):
                    args.append(self.parse_implies())
                    while self.eat(TK_COMMA):
                        args.append(self.parse_implies())
                self.expect(TK_RP)
                return FnCall(tk.v, args)
            return Lit(tk.v)  # bare identifier

        raise SyntaxError(f'Unexpected token {tk.t}({tk.v!r}) at position {tk.p}')

    def parse_list(self):
        self.expect(TK_LB)
        items = []
        if not self.at(TK_RB):
            item = self.parse_implies()
            items.append(item)
            while self.eat(TK_COMMA):
                items.append(self.parse_implies())
        self.expect(TK_RB)
        # Check if this is a quantity: number followed by string
        # handled at evaluation time instead
        return ListExpr(items)

    def parse_if(self):
        self.expect(TK_KW, 'if')
        cond = self.parse_implies()
        self.expect(TK_KW, 'then')
        then_ = self.parse_implies()
        self.expect(TK_KW, 'else')
        else_ = self.parse_implies()
        return IfExpr(cond, then_, else_)

    def parse_case(self):
        self.expect(TK_KW, 'case')
        comparand = None
        if not self.at(TK_KW, 'when'):
            comparand = self.parse_implies()
        whens = []
        while self.eat(TK_KW, 'when'):
            cond = self.parse_implies()
            self.expect(TK_KW, 'then')
            result = self.parse_implies()
            whens.append((cond, result))
        self.expect(TK_KW, 'else')
        else_ = self.parse_implies()
        self.expect(TK_KW, 'end')
        return CaseExpr(comparand, whens, else_)

    def parse_interval(self):
        self.expect(TK_KW, 'Interval')
        lc = True
        if self.eat(TK_LS):
            lc = True
        elif self.eat(TK_LP):
            lc = False
        else:
            raise SyntaxError("Expected '[' or '(' after 'Interval'")
        low = self.parse_implies()
        self.expect(TK_COMMA)
        high = self.parse_implies()
        hc = True
        if self.eat(TK_RS):
            hc = True
        elif self.eat(TK_RP):
            hc = False
        else:
            raise SyntaxError("Expected ']' or ')' to close Interval")
        return IntervalExpr(low, high, lc, hc)


# ═══════════════════════════════════════════════════════════════════════
# LITERAL PARSERS
# ═══════════════════════════════════════════════════════════════════════

def parse_cql_string(tok_val):
    """Parse a CQL string literal like 'hello' or 'it\\'s'"""
    s = tok_val[1:-1]  # strip outer quotes
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i+1 < len(s):
            c = s[i+1]
            if c == 'n': result.append('\n')
            elif c == 'r': result.append('\r')
            elif c == 't': result.append('\t')
            elif c == 'f': result.append('\f')
            elif c == '\\': result.append('\\')
            elif c == "'": result.append("'")
            elif c == '"': result.append('"')
            elif c == '/': result.append('/')
            elif c == '`': result.append('`')
            elif c == 'u' and i+5 < len(s):
                code = int(s[i+2:i+6], 16)
                result.append(chr(code))
                i += 6; continue
            else: result.append(c)
            i += 2
        else:
            result.append(s[i]); i += 1
    return ''.join(result)

def parse_datetime_literal(tok_val):
    """Parse @YYYY-MM-DDThh:mm:ss.fff[Z|+hh:mm]"""
    s = tok_val[1:]  # strip '@'
    tz = None
    if s.endswith('Z'):
        tz = 'Z'; s = s[:-1]
    elif re.search(r'[+-]\d{2}:\d{2}$', s):
        tz = s[-6:]; s = s[:-6]

    parts = re.split(r'[-T:.]', s)
    parts = [int(p) for p in parts if p]
    fields = [None]*7
    for i, v in enumerate(parts):
        if i < 7: fields[i] = v
    return CqlDateTime(*fields, tz=tz)

def parse_time_literal(tok_val):
    """Parse @Thh:mm:ss.fff"""
    s = tok_val[2:]  # strip '@T'
    parts = re.split(r'[:.]', s)
    parts = [int(p) for p in parts if p]
    fields = [None]*4
    for i, v in enumerate(parts):
        if i < 4: fields[i] = v
    return CqlTime(*fields)


# ═══════════════════════════════════════════════════════════════════════
# EVALUATOR
# ═══════════════════════════════════════════════════════════════════════

CQL_DECIMAL_STEP = Decimal('0.00000001')  # 10^-8
CQL_MAX_INT = 2147483647
CQL_MIN_INT = -2147483648
CQL_MAX_LONG = 9223372036854775807
CQL_MIN_LONG = -9223372036854775808
CQL_MAX_DEC = Decimal('99999999999999999999.99999999')
CQL_MIN_DEC = Decimal('-99999999999999999999.99999999')

def ev(node):
    """Evaluate an AST node."""
    if isinstance(node, Lit):
        return node.val

    if isinstance(node, UnaryOp):
        val = ev(node.operand)
        if node.op == '-':
            return eval_negate(val)
        if node.op == 'not':
            if is_null(val): return NULL
            return not val
        return NULL

    if isinstance(node, BinOp):
        return eval_binop(node)

    if isinstance(node, FnCall):
        return eval_function(node)

    if isinstance(node, IfExpr):
        cond = ev(node.cond)
        if cond is True:
            return ev(node.then_)
        return ev(node.else_)

    if isinstance(node, CaseExpr):
        if node.comparand is not None:
            comp = ev(node.comparand)
            for cond, result in node.whens:
                c = ev(cond)
                if not is_null(comp) and not is_null(c) and cql_equal(comp, c) is True:
                    return ev(result)
        else:
            for cond, result in node.whens:
                c = ev(cond)
                if c is True:
                    return ev(result)
        return ev(node.else_)

    if isinstance(node, ListExpr):
        items = [ev(it) for it in node.items]
        return items

    if isinstance(node, IntervalExpr):
        return CqlInterval(ev(node.low), ev(node.high), node.lc, node.hc)

    if isinstance(node, IndexExpr):
        base = ev(node.base)
        idx = ev(node.idx)
        if is_null(base) or is_null(idx): return NULL
        if isinstance(base, list):
            if isinstance(idx, int) and 0 <= idx < len(base):
                return base[idx]
            return NULL
        if isinstance(base, str):
            if isinstance(idx, int) and 0 <= idx < len(base):
                return base[idx]
            return NULL
        return NULL

    if isinstance(node, PredSucc):
        val = ev(node.operand)
        if is_null(val): return NULL
        if node.op == 'predecessor':
            return eval_predecessor(val)
        return eval_successor(val)

    if isinstance(node, MinMax):
        return eval_minmax(node.op, node.typ)

    if isinstance(node, TypeTest):
        val = ev(node.operand)
        if node.test == 'is null':
            return is_null(val)
        if node.test == 'is not null':
            return not is_null(val)
        if node.test == 'is true':
            return val is True
        if node.test == 'is false':
            return val is False
        return NULL

    if isinstance(node, TypeCast):
        val = ev(node.operand)
        # 'null as Type' just returns null
        if is_null(val): return NULL
        return val

    if isinstance(node, BetweenExpr):
        val = ev(node.operand)
        low = ev(node.low)
        high = ev(node.high)
        if is_null(val) or is_null(low) or is_null(high): return NULL
        r1 = cql_compare(val, low)
        r2 = cql_compare(val, high)
        if r1 is None or r2 is None: return NULL
        return r1 >= 0 and r2 <= 0

    if isinstance(node, TupleExpr):
        fields = {name: ev(val) for name, val in node.fields}
        return CqlTuple(fields)

    if isinstance(node, QuantityExpr):
        val = ev(node.value)
        return CqlQuantity(val, node.unit)

    if isinstance(node, MemberExpr):
        obj = ev(node.obj)
        if isinstance(obj, CqlTuple):
            return obj.fields.get(node.member, NULL)
        return NULL

    return NULL


# ── Binary operator evaluation ──

def eval_binop(node):
    op = node.op

    # Short-circuit logical operators
    if op == 'and':
        l = ev(node.l)
        r = ev(node.r)
        return cql_and(l, r)
    if op == 'or':
        l = ev(node.l)
        r = ev(node.r)
        return cql_or(l, r)
    if op == 'xor':
        l = ev(node.l)
        r = ev(node.r)
        return cql_xor(l, r)
    if op == 'implies':
        l = ev(node.l)
        r = ev(node.r)
        return cql_implies(l, r)

    # Equality / equivalence
    if op == '=':
        l = ev(node.l); r = ev(node.r)
        return cql_equal(l, r)
    if op == '!=':
        l = ev(node.l); r = ev(node.r)
        eq = cql_equal(l, r)
        if is_null(eq): return NULL
        return not eq
    if op == '~':
        l = ev(node.l); r = ev(node.r)
        return cql_equivalent(l, r)
    if op == '!~':
        l = ev(node.l); r = ev(node.r)
        return not cql_equivalent(l, r)

    # Comparison
    if op in ('<', '>', '<=', '>='):
        l = ev(node.l); r = ev(node.r)
        if is_null(l) or is_null(r): return NULL
        cmp = cql_compare(l, r)
        if cmp is None: return NULL
        if op == '<': return cmp < 0
        if op == '>': return cmp > 0
        if op == '<=': return cmp <= 0
        if op == '>=': return cmp >= 0

    # Arithmetic
    if op in ('+', '-', '*', '/', 'div', 'mod', '^'):
        l = ev(node.l); r = ev(node.r)
        return eval_arithmetic(op, l, r)

    # String concatenation with &
    if op == '&':
        l = ev(node.l); r = ev(node.r)
        ls = '' if is_null(l) else str(l)
        rs = '' if is_null(r) else str(r)
        return ls + rs

    # Set operations
    if op == 'union':
        l = ev(node.l); r = ev(node.r)
        return eval_union(l, r)
    if op == 'intersect':
        l = ev(node.l); r = ev(node.r)
        return eval_intersect(l, r)
    if op == 'except':
        l = ev(node.l); r = ev(node.r)
        return eval_except(l, r)
    if op == 'in':
        l = ev(node.l); r = ev(node.r)
        return eval_in(l, r)
    if op == 'contains':
        l = ev(node.l); r = ev(node.r)
        return eval_in(r, l)
    if op == 'includes':
        l = ev(node.l); r = ev(node.r)
        return eval_includes(l, r)
    if op == 'included in':
        l = ev(node.l); r = ev(node.r)
        return eval_includes(r, l)
    if op == 'properly includes':
        l = ev(node.l); r = ev(node.r)
        return eval_properly_includes(l, r)
    if op == 'properly included in':
        l = ev(node.l); r = ev(node.r)
        return eval_properly_includes(r, l)

    return NULL


# ── Three-valued logic ──

def cql_and(l, r):
    if l is False or r is False: return False
    if is_null(l) or is_null(r): return NULL
    return l and r

def cql_or(l, r):
    if l is True or r is True: return True
    if is_null(l) or is_null(r): return NULL
    return l or r

def cql_xor(l, r):
    if is_null(l) or is_null(r): return NULL
    return l != r  # bool xor

def cql_implies(l, r):
    if l is False: return True
    if l is True:
        if is_null(r): return NULL
        return r
    # l is null
    if r is True: return True
    return NULL


# ── Equality / Equivalence ──

def cql_equal(l, r):
    if is_null(l) or is_null(r): return NULL
    l, r = coerce_types(l, r)
    if isinstance(l, list) and isinstance(r, list):
        return list_equal(l, r)
    if isinstance(l, Decimal) and isinstance(r, Decimal):
        return l == r
    return l == r

def list_equal(l, r):
    if len(l) != len(r): return False
    result = True
    for a, b in zip(l, r):
        eq = cql_equal(a, b)
        if eq is False: return False
        if is_null(eq): result = NULL
    return result

def cql_equivalent(l, r):
    if is_null(l) and is_null(r): return True
    if is_null(l) or is_null(r): return False
    l, r = coerce_types(l, r)
    if isinstance(l, list) and isinstance(r, list):
        if len(l) != len(r): return False
        for a, b in zip(l, r):
            if not cql_equivalent(a, b): return False
        return True
    if isinstance(l, Decimal) and isinstance(r, Decimal):
        return l == r
    return l == r


# ── Type coercion ──

def coerce_types(l, r):
    """Promote Integer to Decimal or Long as needed."""
    if isinstance(l, int) and not isinstance(l, bool):
        if isinstance(r, Decimal):
            return Decimal(l), r
        if isinstance(r, CqlLong):
            return CqlLong(l), r
    if isinstance(r, int) and not isinstance(r, bool):
        if isinstance(l, Decimal):
            return l, Decimal(r)
        if isinstance(l, CqlLong):
            return l, CqlLong(r)
    return l, r


# ── Comparison ──

def cql_compare(l, r):
    """Returns -1, 0, or 1 for comparison, or None if incomparable."""
    l, r = coerce_types(l, r)
    try:
        if isinstance(l, CqlLong) and isinstance(r, CqlLong):
            return (l.value > r.value) - (l.value < r.value)
        if isinstance(l, CqlQuantity) and isinstance(r, CqlQuantity):
            if l.unit != r.unit: return None
            return (l.value > r.value) - (l.value < r.value)
        if type(l) != type(r) and not (isinstance(l, (int, Decimal)) and isinstance(r, (int, Decimal))):
            return None
        if l < r: return -1
        if l > r: return 1
        if l == r: return 0
        return None
    except TypeError:
        return None


# ── Arithmetic ──

def eval_arithmetic(op, l, r):
    if is_null(l) or is_null(r): return NULL

    # String concatenation with +
    if op == '+' and isinstance(l, str) and isinstance(r, str):
        return l + r
    if op == '+' and isinstance(l, str):
        if is_null(r): return NULL
        return l + str(r)

    # Quantity arithmetic
    if isinstance(l, CqlQuantity) or isinstance(r, CqlQuantity):
        return eval_quantity_arithmetic(op, l, r)

    # Long arithmetic
    if isinstance(l, CqlLong) or isinstance(r, CqlLong):
        return eval_long_arithmetic(op, l, r)

    l, r = coerce_types(l, r)

    if op == '+':
        if isinstance(l, Decimal): return l + r
        return l + r
    if op == '-':
        if isinstance(l, Decimal): return l - r
        return l - r
    if op == '*':
        if isinstance(l, Decimal): return l * r
        return l * r
    if op == '/':
        if isinstance(r, Decimal) and r == 0: return NULL
        if isinstance(r, int) and r == 0: return NULL
        if isinstance(l, int) and isinstance(r, int):
            return Decimal(l) / Decimal(r)
        if isinstance(l, Decimal):
            return l / r
        return Decimal(l) / Decimal(r)
    if op == 'div':
        if isinstance(r, Decimal) and r == 0: return NULL
        if isinstance(r, int) and r == 0: return NULL
        if isinstance(l, int) and isinstance(r, int):
            # Integer truncated division: truncate towards zero
            return int_truncated_div(l, r)
        l_d = l if isinstance(l, Decimal) else Decimal(l)
        r_d = r if isinstance(r, Decimal) else Decimal(r)
        if r_d == 0: return NULL
        result = l_d / r_d
        return Decimal(int(result)) if result >= 0 else Decimal(-int(-result))
    if op == 'mod':
        if isinstance(r, Decimal) and r == 0: return NULL
        if isinstance(r, int) and r == 0: return NULL
        if isinstance(l, int) and isinstance(r, int):
            # CQL mod: result has same sign as dividend
            return l - int_truncated_div(l, r) * r
        l_d = l if isinstance(l, Decimal) else Decimal(l)
        r_d = r if isinstance(r, Decimal) else Decimal(r)
        if r_d == 0: return NULL
        div_result = l_d / r_d
        trunc = Decimal(int(div_result)) if div_result >= 0 else Decimal(-int(-div_result))
        return l_d - trunc * r_d
    if op == '^':
        return eval_power_op(l, r)

    return NULL

def int_truncated_div(a, b):
    """Truncated division (towards zero)."""
    if b == 0: return NULL
    sign = -1 if (a < 0) != (b < 0) else 1
    return sign * (abs(a) // abs(b))

def eval_power_op(l, r):
    if isinstance(l, int) and isinstance(r, int) and not isinstance(l, bool) and not isinstance(r, bool):
        if r < 0:
            return Decimal(l) ** Decimal(r)
        return l ** r
    l_d = l if isinstance(l, Decimal) else Decimal(l)
    r_d = r if isinstance(r, Decimal) else Decimal(r)
    try:
        return l_d ** r_d
    except (InvalidOperation, OverflowError):
        return NULL

def eval_long_arithmetic(op, l, r):
    lv = l.value if isinstance(l, CqlLong) else l
    rv = r.value if isinstance(r, CqlLong) else r
    if isinstance(l, CqlLong) and isinstance(r, CqlLong):
        if op == '+': return CqlLong(lv + rv)
        if op == '-': return CqlLong(lv - rv)
        if op == '*': return CqlLong(lv * rv)
        if op == '/':
            if rv == 0: return NULL
            return Decimal(lv) / Decimal(rv)
        if op == 'div':
            if rv == 0: return NULL
            return CqlLong(int_truncated_div(lv, rv))
        if op == 'mod':
            if rv == 0: return NULL
            return CqlLong(lv - int_truncated_div(lv, rv) * rv)
        if op == '^':
            if rv < 0:
                return Decimal(lv) ** Decimal(rv)
            return CqlLong(lv ** rv)
    # Mixed Long with Int → promote to Long
    if isinstance(l, CqlLong) and isinstance(r, int) and not isinstance(r, bool):
        return eval_long_arithmetic(op, l, CqlLong(r))
    if isinstance(r, CqlLong) and isinstance(l, int) and not isinstance(l, bool):
        return eval_long_arithmetic(op, CqlLong(l), r)
    return NULL

def eval_quantity_arithmetic(op, l, r):
    if isinstance(l, CqlQuantity) and isinstance(r, CqlQuantity):
        if op == '+': return CqlQuantity(l.value + r.value, l.unit)
        if op == '-': return CqlQuantity(l.value - r.value, l.unit)
        if op == '*': return CqlQuantity(l.value * r.value, l.unit + '2')
        if op == '/':
            if r.value == 0: return NULL
            return CqlQuantity(l.value / r.value, '1')
    if isinstance(l, CqlQuantity):
        rv = r if isinstance(r, Decimal) else Decimal(str(r)) if isinstance(r, (int, float)) else None
        if rv is None: return NULL
        if op == '*': return CqlQuantity(l.value * rv, l.unit)
        if op == '/':
            if rv == 0: return NULL
            return CqlQuantity(l.value / rv, l.unit)
    return NULL


# ── Negation ──

def eval_negate(val):
    if is_null(val): return NULL
    if isinstance(val, int) and not isinstance(val, bool): return -val
    if isinstance(val, Decimal): return -val
    if isinstance(val, CqlLong): return CqlLong(-val.value)
    if isinstance(val, CqlQuantity): return CqlQuantity(-val.value, val.unit)
    return NULL


# ── Predecessor / Successor ──

def eval_predecessor(val):
    if isinstance(val, int) and not isinstance(val, bool):
        return val - 1
    if isinstance(val, Decimal):
        return val - CQL_DECIMAL_STEP
    if isinstance(val, CqlLong):
        return CqlLong(val.value - 1)
    if isinstance(val, CqlQuantity):
        return CqlQuantity(val.value - CQL_DECIMAL_STEP, val.unit)
    if isinstance(val, CqlDateTime):
        return dt_add(val, -1)
    if isinstance(val, CqlTime):
        return time_add(val, -1)
    return NULL

def eval_successor(val):
    if isinstance(val, int) and not isinstance(val, bool):
        return val + 1
    if isinstance(val, Decimal):
        return val + CQL_DECIMAL_STEP
    if isinstance(val, CqlLong):
        return CqlLong(val.value + 1)
    if isinstance(val, CqlQuantity):
        return CqlQuantity(val.value + CQL_DECIMAL_STEP, val.unit)
    if isinstance(val, CqlDateTime):
        return dt_add(val, 1)
    if isinstance(val, CqlTime):
        return time_add(val, 1)
    return NULL

def dt_add(dt, delta):
    """Add delta units at the DateTime's precision level."""
    import datetime as _dt
    if dt.millisecond is not None:
        d = _dt.datetime(dt.year, dt.month or 1, dt.day or 1,
                         dt.hour or 0, dt.minute or 0, dt.second or 0,
                         (dt.millisecond or 0) * 1000)
        d += _dt.timedelta(milliseconds=delta)
        return CqlDateTime(d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000)
    if dt.second is not None:
        d = _dt.datetime(dt.year, dt.month or 1, dt.day or 1,
                         dt.hour or 0, dt.minute or 0, dt.second or 0)
        d += _dt.timedelta(seconds=delta)
        return CqlDateTime(d.year, d.month, d.day, d.hour, d.minute, d.second)
    if dt.minute is not None:
        d = _dt.datetime(dt.year, dt.month or 1, dt.day or 1,
                         dt.hour or 0, dt.minute or 0)
        d += _dt.timedelta(minutes=delta)
        return CqlDateTime(d.year, d.month, d.day, d.hour, d.minute)
    if dt.hour is not None:
        d = _dt.datetime(dt.year, dt.month or 1, dt.day or 1, dt.hour or 0)
        d += _dt.timedelta(hours=delta)
        return CqlDateTime(d.year, d.month, d.day, d.hour)
    if dt.day is not None:
        d = _dt.date(dt.year, dt.month or 1, dt.day or 1)
        d += _dt.timedelta(days=delta)
        return CqlDateTime(d.year, d.month, d.day)
    if dt.month is not None:
        m = (dt.year * 12 + (dt.month - 1) + delta)
        return CqlDateTime(m // 12, m % 12 + 1)
    return CqlDateTime(dt.year + delta)

def time_add(t, delta):
    """Add delta units at the Time's precision level."""
    if t.millisecond is not None:
        total_ms = (t.hour or 0)*3600000 + (t.minute or 0)*60000 + (t.second or 0)*1000 + (t.millisecond or 0) + delta
        h = (total_ms // 3600000) % 24
        m = (total_ms % 3600000) // 60000
        s = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        return CqlTime(h, m, s, ms)
    if t.second is not None:
        total_s = (t.hour or 0)*3600 + (t.minute or 0)*60 + (t.second or 0) + delta
        return CqlTime((total_s // 3600) % 24, (total_s % 3600) // 60, total_s % 60)
    if t.minute is not None:
        total_m = (t.hour or 0)*60 + (t.minute or 0) + delta
        return CqlTime((total_m // 60) % 24, total_m % 60)
    return CqlTime(((t.hour or 0) + delta) % 24)


# ── Min/Max values ──

def eval_minmax(op, typ):
    if op == 'minimum':
        if typ == 'Integer': return CQL_MIN_INT
        if typ == 'Long': return CqlLong(CQL_MIN_LONG)
        if typ == 'Decimal': return CQL_MIN_DEC
        if typ == 'DateTime': return CqlDateTime(1, 1, 1, 0, 0, 0, 0, tz='Z')
        if typ == 'Date': return CqlDateTime(1, 1, 1)
        if typ == 'Time': return CqlTime(0, 0, 0, 0)
    if op == 'maximum':
        if typ == 'Integer': return CQL_MAX_INT
        if typ == 'Long': return CqlLong(CQL_MAX_LONG)
        if typ == 'Decimal': return CQL_MAX_DEC
        if typ == 'DateTime': return CqlDateTime(9999, 12, 31, 23, 59, 59, 999, tz='Z')
        if typ == 'Date': return CqlDateTime(9999, 12, 31)
        if typ == 'Time': return CqlTime(23, 59, 59, 999)
    return NULL


# ── Built-in functions ──

def eval_function(node):
    name = node.name
    args_nodes = node.args

    if name == 'DateTime':
        args = [ev(a) for a in args_nodes]
        if len(args) == 1 and is_null(args[0]):
            return NULL
        fields = [None]*7
        for i, a in enumerate(args):
            if i < 7:
                fields[i] = None if is_null(a) else a
        return CqlDateTime(*fields)

    if name == 'Time':
        args = [ev(a) for a in args_nodes]
        fields = [None]*4
        for i, a in enumerate(args):
            if i < 4: fields[i] = None if is_null(a) else a
        return CqlTime(*fields)

    if name == 'Abs':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, int) and not isinstance(v, bool): return abs(v)
        if isinstance(v, Decimal): return abs(v)
        if isinstance(v, CqlLong): return CqlLong(abs(v.value))
        if isinstance(v, CqlQuantity): return CqlQuantity(abs(v.value), v.unit)
        return NULL

    if name == 'Ceiling':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, int) and not isinstance(v, bool): return v
        if isinstance(v, Decimal):
            import math as _m
            if v > CQL_MAX_INT or v < CQL_MIN_INT:
                # Check if ceiling would overflow
                c = int(v) if v == int(v) else int(v) + (1 if v > 0 else 0)
                if c > CQL_MAX_INT or c < CQL_MIN_INT: return NULL
                return c
            c = int(v) if v == int(v) else int(v) + (1 if v > 0 else 0)
            if v < 0 and v != int(v):
                c = int(v)
            return c
        return NULL

    if name == 'Floor':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, int) and not isinstance(v, bool): return v
        if isinstance(v, Decimal):
            if v >= 0:
                f = int(v)
            else:
                f = int(v) if v == int(v) else int(v) - 1
            if f > CQL_MAX_INT or f < CQL_MIN_INT: return NULL
            return f
        return NULL

    if name == 'Truncate':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, int) and not isinstance(v, bool): return v
        if isinstance(v, Decimal):
            return int(v)  # truncate towards zero
        return NULL

    if name == 'Round':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        prec = 0
        if len(args_nodes) > 1:
            prec = ev(args_nodes[1])
            if is_null(prec): prec = 0
        if isinstance(v, int) and not isinstance(v, bool):
            v = Decimal(v)
        if isinstance(v, Decimal):
            if prec == 0:
                # Round half away from zero
                return v.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            else:
                quant = Decimal(10) ** (-prec)
                return v.quantize(quant, rounding=ROUND_HALF_UP)
        return NULL

    if name == 'Exp':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        num = to_number(v)
        if num is None: return NULL
        try:
            return Decimal(str(math.exp(float(num))))
        except (OverflowError, ValueError):
            return NULL

    if name == 'Ln':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        num = to_number(v)
        if num is None: return NULL
        if num <= 0:
            if num == 0: return NULL  # -infinity
            return NULL  # undefined
        try:
            return Decimal(str(math.log(float(num))))
        except (ValueError, OverflowError):
            return NULL

    if name == 'Log':
        v = ev(args_nodes[0])
        base = ev(args_nodes[1])
        if is_null(v) or is_null(base): return NULL
        vn = to_number(v)
        bn = to_number(base)
        if vn is None or bn is None: return NULL
        if bn == 1: return NULL
        if vn <= 0: return NULL
        try:
            return Decimal(str(math.log(float(vn), float(bn))))
        except (ValueError, ZeroDivisionError, OverflowError):
            return NULL

    if name == 'Power':
        b = ev(args_nodes[0])
        e = ev(args_nodes[1])
        if is_null(b) or is_null(e): return NULL
        return eval_arithmetic('^', b, e)

    if name == 'First':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, list):
            return v[0] if len(v) > 0 else NULL
        return NULL

    if name == 'Last':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, list):
            return v[-1] if len(v) > 0 else NULL
        return NULL

    if name == 'Length':
        v = ev(args_nodes[0])
        if is_null(v): return 0
        if isinstance(v, list): return len(v)
        if isinstance(v, str): return len(v)
        return NULL

    if name == 'Exists':
        v = ev(args_nodes[0])
        if is_null(v): return False
        if isinstance(v, list):
            return any(not is_null(x) for x in v)
        return True

    if name == 'IndexOf':
        lst = ev(args_nodes[0])
        item = ev(args_nodes[1])
        if is_null(lst) or is_null(item): return NULL
        if isinstance(lst, list):
            for i, el in enumerate(lst):
                eq = cql_equal(el, item)
                if eq is True: return i
            return -1
        return NULL

    if name == 'Flatten':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, list):
                    result.extend(item)
                else:
                    result.append(item)
            return result
        return NULL

    if name == 'distinct':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, list):
            result = []
            for item in v:
                found = False
                for existing in result:
                    if cql_equivalent(item, existing):
                        found = True; break
                if not found:
                    result.append(item)
            return result
        return NULL

    if name == 'flatten':
        return eval_function(type(node)(name='Flatten', args=args_nodes))

    if name == 'singleton from':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, list):
            if len(v) == 0: return NULL
            if len(v) == 1: return v[0]
            raise ValueError("Expected a list with at most one element")
        return NULL

    if name == 'Combine':
        if is_null(ev(args_nodes[0])): return NULL
        lst = ev(args_nodes[0])
        if not isinstance(lst, list): return NULL
        if len(lst) == 0: return NULL
        sep = ''
        if len(args_nodes) > 1:
            sep = ev(args_nodes[1])
            if is_null(sep): sep = ''
        parts = [x for x in lst if not is_null(x)]
        if not parts: return NULL
        return sep.join(str(x) for x in parts)

    if name == 'Concatenate':
        a = ev(args_nodes[0])
        b = ev(args_nodes[1])
        if is_null(a) or is_null(b): return NULL
        return str(a) + str(b)

    if name == 'Skip':
        lst = ev(args_nodes[0])
        count = ev(args_nodes[1])
        if is_null(lst): return NULL
        if is_null(count): return lst
        if isinstance(lst, list):
            return lst[count:]
        return NULL

    if name == 'Take':
        lst = ev(args_nodes[0])
        count = ev(args_nodes[1])
        if is_null(lst): return NULL
        if is_null(count): return []
        if isinstance(lst, list):
            return lst[:count]
        return NULL

    if name == 'Tail':
        lst = ev(args_nodes[0])
        if is_null(lst): return NULL
        if isinstance(lst, list):
            return lst[1:] if len(lst) > 0 else []
        return NULL

    if name == 'Slice':
        lst = ev(args_nodes[0])
        if is_null(lst): return NULL
        if not isinstance(lst, list): return NULL
        if len(args_nodes) == 1:
            return lst
        start = ev(args_nodes[1]) if len(args_nodes) > 1 else None
        end = ev(args_nodes[2]) if len(args_nodes) > 2 else None
        if is_null(start): start = 0
        if start < 0: start = max(0, len(lst) + start)
        if is_null(end) or len(args_nodes) <= 2:
            return lst[start:]
        if end < 0: end = len(lst) + end
        return lst[start:end]

    if name == 'HighBoundary':
        v = ev(args_nodes[0])
        prec = ev(args_nodes[1]) if len(args_nodes) > 1 else NULL
        if is_null(v): return NULL
        if isinstance(v, Decimal):
            if is_null(prec): prec = 8
            s = str(v)
            if '.' in s:
                int_part, frac = s.split('.')
                cur_prec = len(frac)
            else:
                int_part = s; frac = ''; cur_prec = 0
            if cur_prec < prec:
                frac = frac + '9' * (prec - cur_prec)
            return Decimal(int_part + '.' + frac[:prec])
        return NULL

    if name == 'LowBoundary':
        v = ev(args_nodes[0])
        prec = ev(args_nodes[1]) if len(args_nodes) > 1 else NULL
        if is_null(v): return NULL
        if isinstance(v, Decimal):
            if is_null(prec): prec = 8
            s = str(v)
            if '.' in s:
                int_part, frac = s.split('.')
                cur_prec = len(frac)
            else:
                int_part = s; frac = ''; cur_prec = 0
            if cur_prec < prec:
                frac = frac + '0' * (prec - cur_prec)
            return Decimal(int_part + '.' + frac[:prec])
        return NULL

    if name == 'Precision':
        v = ev(args_nodes[0])
        if is_null(v): return NULL
        if isinstance(v, Decimal):
            s = str(v)
            if '.' in s:
                return len(s.split('.')[1])
            return 0
        return NULL

    return NULL


# ── List set operations ──

def eval_union(l, r):
    if is_null(l) and is_null(r): return NULL
    if is_null(l): l = []
    if is_null(r): r = []
    if not isinstance(l, list) or not isinstance(r, list): return NULL
    result = list(l)
    for item in r:
        found = False
        for existing in result:
            if cql_equivalent(item, existing):
                found = True; break
        if not found:
            result.append(item)
    return result

def eval_intersect(l, r):
    if is_null(l) or is_null(r): return NULL
    if not isinstance(l, list) or not isinstance(r, list): return NULL
    result = []
    for item in l:
        for item2 in r:
            if cql_equivalent(item, item2):
                found_in_result = False
                for existing in result:
                    if cql_equivalent(item, existing):
                        found_in_result = True; break
                if not found_in_result:
                    result.append(item)
                break
    return result

def eval_except(l, r):
    if is_null(l): return NULL
    if is_null(r): return l if isinstance(l, list) else NULL
    if not isinstance(l, list): return NULL
    if not isinstance(r, list): r = []
    result = []
    for item in l:
        found = False
        for item2 in r:
            if cql_equivalent(item, item2):
                found = True; break
        if not found:
            result.append(item)
    return result

def eval_in(element, lst):
    if is_null(lst):
        if isinstance(lst, list): pass
        else: return False
    if not isinstance(lst, list): return False
    if len(lst) == 0: return False
    for item in lst:
        eq = cql_equal(element, item)
        if eq is True: return True
        if is_null(element) and is_null(item): return True
    return False

def eval_includes(l, r):
    """Does l include all of r?"""
    if is_null(l) or is_null(r): return NULL
    if isinstance(r, list):
        for item in r:
            if not eval_in(item, l):
                return False
        return True
    # Single element
    return eval_in(r, l)

def eval_properly_includes(l, r):
    """Does l properly include r? (includes and is strictly larger)"""
    if is_null(l) or is_null(r):
        if is_null(l) and not isinstance(r, list): return False
        if is_null(l): return False
        return False
    if isinstance(r, list):
        if not isinstance(l, list): return False
        if len(l) <= len(r):
            # Check if they're the same
            inc = eval_includes(l, r)
            if inc is True and len(l) == len(r):
                return False
            return False
        return eval_includes(l, r) is True
    # Single element properly contained
    if not isinstance(l, list): return False
    if len(l) <= 1:
        if len(l) == 1 and eval_in(r, l):
            return False
        return False
    return eval_in(r, l)


# ── Helpers ──

def to_number(v):
    """Convert a CQL value to a Python number (float-compatible), or None."""
    if is_null(v): return None
    if isinstance(v, bool): return None
    if isinstance(v, int): return v
    if isinstance(v, Decimal): return v
    if isinstance(v, CqlLong): return v.value
    if isinstance(v, float): return v
    return None


# ═══════════════════════════════════════════════════════════════════════
# FORMATTER
# ═══════════════════════════════════════════════════════════════════════

def format_cql(val):
    """Format a CQL value as its canonical string representation."""
    if is_null(val):
        return 'null'
    if val is True:
        return 'true'
    if val is False:
        return 'false'
    if isinstance(val, int) and not isinstance(val, bool):
        return str(val)
    if isinstance(val, Decimal):
        return format_decimal(val)
    if isinstance(val, CqlLong):
        return f'{val.value}L'
    if isinstance(val, str):
        escaped = val.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')
        return f"'{escaped}'"
    if isinstance(val, list):
        if len(val) == 0:
            return '{}'
        items = ', '.join(format_cql(x) for x in val)
        return '{' + items + '}'
    if isinstance(val, CqlDateTime):
        return format_datetime(val)
    if isinstance(val, CqlTime):
        return format_time(val)
    if isinstance(val, CqlInterval):
        lb = '[' if val.low_closed else '('
        rb = ']' if val.high_closed else ')'
        return f'Interval{lb}{format_cql(val.low)}, {format_cql(val.high)}{rb}'
    if isinstance(val, CqlQuantity):
        return f"{format_decimal(val.value)}'{val.unit}'"
    if isinstance(val, CqlTuple):
        parts = ', '.join(f'{k}: {format_cql(v)}' for k, v in val.fields.items())
        return 'Tuple {' + parts + '}'
    return str(val)

def format_decimal(v):
    """Format a Decimal, ensuring at least one decimal place."""
    if v != v:
        return 'null'
    # Normalize: remove trailing zeros but keep at least one decimal digit
    # Also handle negative zero
    v = v.normalize()
    if v == 0:
        v = abs(v)  # remove negative zero
    s = str(v)
    if 'E' in s or 'e' in s:
        # Scientific notation — convert back
        s = str(v.quantize(Decimal(1)) if v == int(v) else v.normalize())
        if 'E' in s or 'e' in s:
            s = f'{float(v):.20f}'.rstrip('0')
    if '.' not in s:
        s += '.0'
    else:
        int_part, frac = s.split('.')
        # Strip trailing zeros but keep at least one
        frac = frac.rstrip('0') or '0'
        s = int_part + '.' + frac
    return s

def format_datetime(dt):
    """Format a CqlDateTime as @YYYY-MM-DDThh:mm:ss.fff"""
    if dt.year is None:
        return 'null'
    s = f'@{dt.year:04d}'
    if dt.month is not None:
        s += f'-{dt.month:02d}'
        if dt.day is not None:
            s += f'-{dt.day:02d}'
    s += 'T'
    if dt.hour is not None:
        s += f'{dt.hour:02d}'
        if dt.minute is not None:
            s += f':{dt.minute:02d}'
            if dt.second is not None:
                s += f':{dt.second:02d}'
                if dt.millisecond is not None:
                    s += f'.{dt.millisecond:03d}'
    if dt.tz:
        s += dt.tz
    return s

def format_time(t):
    """Format a CqlTime as @Thh:mm:ss.fff"""
    s = f'@T{t.hour:02d}'
    if t.minute is not None:
        s += f':{t.minute:02d}'
        if t.second is not None:
            s += f':{t.second:02d}'
            if t.millisecond is not None:
                s += f'.{t.millisecond:03d}'
    return s


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def evaluate(expression):
    """Parse and evaluate a CQL expression string."""
    tokens = tokenize(expression)
    parser = Parser(tokens)
    ast = parser.parse()

    # Check for quantity: if result is a number followed by a string token
    # that wasn't consumed, treat the unconsumed part as a unit.
    # This handles patterns like: 5.0 'g'
    if parser.pos < len(tokens) - 1:  # -1 for EOF
        remaining = tokens[parser.pos]
        if remaining.t == TK_STR:
            val = ev(ast)
            unit = parse_cql_string(remaining.v)
            parser.advance()
            if isinstance(val, (int, Decimal)) and not isinstance(val, bool):
                return CqlQuantity(val, unit)

    result = ev(ast)
    return result


def _resolve_identifier(name):
    """Resolve bare identifiers — for now just return as-is."""
    return name
