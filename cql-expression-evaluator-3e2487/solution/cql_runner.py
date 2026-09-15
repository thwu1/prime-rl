#!/usr/bin/env python3
"""CQL Expression Test Runner — evaluates CQL expressions from HL7 XML fixtures.

"""

import sys, os, json, math, re, glob
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, InvalidOperation, getcontext
from xml.etree import ElementTree
from datetime import date as pydate, timedelta

getcontext().prec = 40

sys.path.insert(0, '/app/generated')
from antlr4 import CommonTokenStream, InputStream
from CqlExprLexer import CqlExprLexer
from CqlExprParser import CqlExprParser
from CqlExprVisitor import CqlExprVisitor

# ═══════════════════════ CQL TYPE SYSTEM ═══════════════════════

class CqlNull:
    _inst = None
    def __new__(cls):
        if cls._inst is None: cls._inst = super().__new__(cls)
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
    def __lt__(self, o):
        if isinstance(o, CqlLong): return self.value < o.value
        return NotImplemented
    def __le__(self, o):
        if isinstance(o, CqlLong): return self.value <= o.value
        return NotImplemented
    def __gt__(self, o):
        if isinstance(o, CqlLong): return self.value > o.value
        return NotImplemented
    def __ge__(self, o):
        if isinstance(o, CqlLong): return self.value >= o.value
        return NotImplemented

class CqlDateTime:
    __slots__ = ('year','month','day','hour','minute','second','millisecond','tz')
    def __init__(self, year=None, month=None, day=None, hour=None,
                 minute=None, second=None, millisecond=None, tz=None):
        self.year=year; self.month=month; self.day=day; self.hour=hour
        self.minute=minute; self.second=second; self.millisecond=millisecond; self.tz=tz
    def _fields(self):
        return (self.year, self.month, self.day, self.hour, self.minute, self.second, self.millisecond)
    def _cmp_tuple(self):
        return tuple(0 if x is None else x for x in self._fields())
    def _precision(self):
        f = self._fields()
        for i in range(6, -1, -1):
            if f[i] is not None: return i
        return -1
    def __eq__(self, o):
        if not isinstance(o, CqlDateTime): return NotImplemented
        return self._fields() == o._fields()
    def __hash__(self): return hash(('DT',) + self._fields())
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

class CqlTime:
    __slots__ = ('hour','minute','second','millisecond')
    def __init__(self, hour=None, minute=None, second=None, millisecond=None):
        self.hour=hour; self.minute=minute; self.second=second; self.millisecond=millisecond
    def _fields(self): return (self.hour, self.minute, self.second, self.millisecond)
    def _cmp_tuple(self): return tuple(0 if x is None else x for x in self._fields())
    def __eq__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._fields() == o._fields()
    def __hash__(self): return hash(('T',) + self._fields())
    def __lt__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._cmp_tuple() < o._cmp_tuple()
    def __le__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._cmp_tuple() <= o._cmp_tuple()
    def __gt__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._cmp_tuple() > o._cmp_tuple()
    def __ge__(self, o):
        if not isinstance(o, CqlTime): return NotImplemented
        return self._cmp_tuple() >= o._cmp_tuple()

class CqlQuantity:
    __slots__ = ('value','unit')
    def __init__(self, value, unit):
        self.value = Decimal(str(value)) if not isinstance(value, Decimal) else value
        self.unit = unit
    def __eq__(self, o):
        if not isinstance(o, CqlQuantity): return NotImplemented
        if self.unit != o.unit:
            c = _convert_qty(self, o.unit)
            if c is None: return NotImplemented
            return c.value == o.value
        return self.value == o.value
    def __hash__(self): return hash(('Q', self.value, self.unit))
    def __lt__(self, o):
        if not isinstance(o, CqlQuantity): return NotImplemented
        a, b = _align_qty(self, o)
        if a is None: return NotImplemented
        return a.value < b.value
    def __le__(self, o):
        if not isinstance(o, CqlQuantity): return NotImplemented
        a, b = _align_qty(self, o)
        if a is None: return NotImplemented
        return a.value <= b.value
    def __gt__(self, o):
        if not isinstance(o, CqlQuantity): return NotImplemented
        a, b = _align_qty(self, o)
        if a is None: return NotImplemented
        return a.value > b.value
    def __ge__(self, o):
        if not isinstance(o, CqlQuantity): return NotImplemented
        a, b = _align_qty(self, o)
        if a is None: return NotImplemented
        return a.value >= b.value

# Calendar/time unit conversions
_UNIT_ALIASES = {
    'year': 'year', 'years': 'year', 'a': 'year',
    'month': 'month', 'months': 'month', 'mo': 'month',
    'week': 'week', 'weeks': 'week', 'wk': 'week',
    'day': 'day', 'days': 'day', 'd': 'day',
    'hour': 'hour', 'hours': 'hour', 'h': 'hour',
    'minute': 'minute', 'minutes': 'minute', 'min': 'min',
    'second': 'second', 'seconds': 'second', 's': 'second',
    'millisecond': 'millisecond', 'milliseconds': 'millisecond', 'ms': 'millisecond',
}
_DEFINITE_TO_MS = {
    'millisecond': 1, 'second': 1000, 'minute': 60000, 'min': 60000,
    'hour': 3600000, 'day': 86400000, 'week': 604800000,
}
_CALENDAR_TO_DAYS = {'year': 365, 'month': 30, 'week': 7}

def _normalize_unit(u):
    u2 = u.strip("'").strip('"')
    return _UNIT_ALIASES.get(u2, u2)

def _convert_qty(q, target_unit):
    su = _normalize_unit(q.unit)
    tu = _normalize_unit(target_unit)
    if su == tu: return CqlQuantity(q.value, target_unit)
    if su in _DEFINITE_TO_MS and tu in _DEFINITE_TO_MS:
        factor = Decimal(_DEFINITE_TO_MS[su]) / Decimal(_DEFINITE_TO_MS[tu])
        return CqlQuantity(q.value * factor, target_unit)
    return None

def _align_qty(a, b):
    if _normalize_unit(a.unit) == _normalize_unit(b.unit): return a, b
    c = _convert_qty(a, b.unit)
    if c: return c, b
    c = _convert_qty(b, a.unit)
    if c: return a, c
    return None, None

class CqlInterval:
    __slots__ = ('low','high','low_closed','high_closed')
    def __init__(self, low, high, low_closed=True, high_closed=True):
        self.low=low; self.high=high; self.low_closed=low_closed; self.high_closed=high_closed
    def __eq__(self, o):
        if not isinstance(o, CqlInterval): return NotImplemented
        return (self.low == o.low and self.high == o.high
                and self.low_closed == o.low_closed and self.high_closed == o.high_closed)
    def __hash__(self): return hash(('I', self.low, self.high, self.low_closed, self.high_closed))

class CqlTuple:
    __slots__ = ('elements',)
    def __init__(self, elements): self.elements = dict(elements)
    def __eq__(self, o):
        if not isinstance(o, CqlTuple): return NotImplemented
        return self.elements == o.elements
    def __hash__(self): return hash(('Tuple', tuple(sorted(self.elements.items()))))

# ═══════════════════════ FORMATTER ═══════════════════════

def format_cql(v):
    if is_null(v): return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, int): return str(v)
    if isinstance(v, Decimal):
        # Normalize negative zero
        if v == 0 and v.is_signed():
            v = abs(v)
        # Use fixed-point notation to avoid scientific notation (e.g. 1E-8)
        s = format(v, 'f')
        if '.' not in s: s += '.0'
        return s
    if isinstance(v, CqlLong): return f'{v.value}L'
    if isinstance(v, str): return f"'{v}'"
    if isinstance(v, CqlDateTime):
        parts = [f'{v.year:04d}' if v.year is not None else None]
        if v.month is not None: parts.append(f'{v.month:02d}')
        if v.day is not None: parts.append(f'{v.day:02d}')
        date_part = '-'.join(p for p in parts if p)
        time_parts = []
        if v.hour is not None:
            time_parts.append(f'{v.hour:02d}')
            if v.minute is not None:
                time_parts.append(f'{v.minute:02d}')
                if v.second is not None:
                    time_parts.append(f'{v.second:02d}')
                    if v.millisecond is not None:
                        time_parts[-1] += f'.{v.millisecond:03d}'
        s = '@' + date_part + 'T'
        if time_parts: s += ':'.join(time_parts)
        if v.tz is not None: s += v.tz
        return s
    if isinstance(v, CqlTime):
        parts = []
        if v.hour is not None:
            parts.append(f'{v.hour:02d}')
            if v.minute is not None:
                parts.append(f'{v.minute:02d}')
                if v.second is not None:
                    sec = f'{v.second:02d}'
                    if v.millisecond is not None: sec += f'.{v.millisecond:03d}'
                    parts.append(sec)
        return '@T' + ':'.join(parts)
    if isinstance(v, CqlQuantity):
        val_s = format_cql(v.value) if isinstance(v.value, Decimal) else str(v.value)
        u = v.unit
        if not u.startswith("'"): u = f"'{u}'"
        return f"{val_s}{u}"
    if isinstance(v, list):
        return '{' + ', '.join(format_cql(x) for x in v) + '}'
    if isinstance(v, CqlInterval):
        lb = '[' if v.low_closed else '('
        rb = ']' if v.high_closed else ')'
        return f'Interval{lb}{format_cql(v.low)}, {format_cql(v.high)}{rb}'
    if isinstance(v, CqlTuple):
        pairs = ', '.join(f'{k}: {format_cql(val)}' for k, val in v.elements.items())
        return 'Tuple { ' + pairs + ' }'
    return str(v)


# ═══════════════════════ TYPE HELPERS ═══════════════════════

def _to_decimal(v):
    if is_null(v): return NULL
    if isinstance(v, Decimal): return v
    if isinstance(v, int): return Decimal(v)
    if isinstance(v, CqlLong): return Decimal(v.value)
    return NULL

def _coerce_arith(a, b):
    """Coerce two operands for arithmetic."""
    if is_null(a) or is_null(b): return NULL, NULL
    if isinstance(a, CqlQuantity) and isinstance(b, CqlQuantity):
        return a, b
    if isinstance(a, CqlQuantity) or isinstance(b, CqlQuantity):
        if isinstance(a, CqlQuantity) and isinstance(b, (int, Decimal)):
            return a, CqlQuantity(Decimal(str(b)), a.unit)
        if isinstance(b, CqlQuantity) and isinstance(a, (int, Decimal)):
            return CqlQuantity(Decimal(str(a)), b.unit), b
        return a, b
    if isinstance(a, str) or isinstance(b, str):
        return a, b
    if isinstance(a, CqlLong) and isinstance(b, CqlLong):
        return a, b
    if isinstance(a, CqlLong) and isinstance(b, int):
        return a, CqlLong(b)
    if isinstance(b, CqlLong) and isinstance(a, int):
        return CqlLong(a), b
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return _to_decimal(a), _to_decimal(b)
    return a, b

def _cql_eq(a, b):
    if is_null(a) or is_null(b): return NULL
    a, b = _coerce_arith(a, b)
    if is_null(a): return NULL
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): return False
        results = [_cql_eq(x, y) for x, y in zip(a, b)]
        if any(is_null(r) for r in results): return NULL
        return all(r is True for r in results)
    if isinstance(a, CqlTuple) and isinstance(b, CqlTuple):
        keys = set(a.elements) | set(b.elements)
        has_null = False
        for k in keys:
            va = a.elements.get(k, NULL)
            vb = b.elements.get(k, NULL)
            r = _cql_eq(va, vb)
            if r is False: return False
            if is_null(r): has_null = True
        return NULL if has_null else True
    if isinstance(a, CqlQuantity) and isinstance(b, CqlQuantity):
        aa, bb = _align_qty(a, b)
        if aa is None: return NULL
        return aa.value == bb.value
    if isinstance(a, CqlDateTime) and isinstance(b, CqlDateTime):
        pa, pb = a._precision(), b._precision()
        mp = min(pa, pb)
        fa, fb = a._fields(), b._fields()
        has_null = pa != pb
        for i in range(mp + 1):
            if fa[i] != fb[i]: return False
        return NULL if has_null else True
    if isinstance(a, CqlTime) and isinstance(b, CqlTime):
        return a._fields() == b._fields()
    try:
        return a == b
    except TypeError:
        return NULL

def _cql_equiv(a, b):
    if is_null(a) and is_null(b): return True
    if is_null(a) or is_null(b): return False
    a2, b2 = _coerce_arith(a, b)
    if isinstance(a2, str) and isinstance(b2, str):
        return a2.lower() == b2.lower()
    if isinstance(a2, list) and isinstance(b2, list):
        if len(a2) != len(b2): return False
        return all(_cql_equiv(x, y) for x, y in zip(a2, b2))
    if isinstance(a2, CqlTuple) and isinstance(b2, CqlTuple):
        keys = set(a2.elements) | set(b2.elements)
        return all(_cql_equiv(a2.elements.get(k, NULL), b2.elements.get(k, NULL)) for k in keys)
    if isinstance(a2, CqlQuantity) and isinstance(b2, CqlQuantity):
        nu_a = _normalize_unit(a2.unit)
        nu_b = _normalize_unit(b2.unit)
        if nu_a == nu_b:
            return a2.value == b2.value
        aa, bb = _align_qty(a2, b2)
        if aa is None:
            ca = _cal_to_days(a2)
            cb = _cal_to_days(b2)
            if ca is not None and cb is not None:
                return ca == cb
            return False
        return aa.value == bb.value
    r = _cql_eq(a2, b2)
    if is_null(r): return True
    return r

def _cal_to_days(q):
    nu = _normalize_unit(q.unit)
    if nu in _CALENDAR_TO_DAYS:
        return q.value * Decimal(_CALENDAR_TO_DAYS[nu])
    if nu in _DEFINITE_TO_MS:
        return q.value * Decimal(_DEFINITE_TO_MS[nu]) / Decimal(86400000)
    return None

def _cql_compare(a, b):
    """Returns -1, 0, 1 or NULL."""
    if is_null(a) or is_null(b): return NULL
    a, b = _coerce_arith(a, b)
    if is_null(a): return NULL
    if isinstance(a, CqlDateTime) and isinstance(b, CqlDateTime):
        pa, pb = a._precision(), b._precision()
        mp = min(pa, pb)
        fa, fb = a._fields(), b._fields()
        for i in range(mp + 1):
            if fa[i] < fb[i]: return -1
            if fa[i] > fb[i]: return 1
        if pa != pb: return NULL
        return 0
    try:
        if a < b: return -1
        if a > b: return 1
        if a == b: return 0
        return NULL
    except TypeError:
        return NULL


# ═══════════════════════ LIST INCLUSION HELPERS ═══════════════════════

def _list_includes(container, item):
    """CQL 'includes' operator: list-to-list or element-level."""
    if isinstance(item, list):
        # List-to-list: every element of item must be in container
        if is_null(container): return NULL
        if not isinstance(container, list): container = [container]
        for elem in item:
            found = any(_cql_equiv(elem, c) for c in container)
            if not found: return False
        return True
    else:
        # Element-level (same as 'contains')
        if is_null(container) or is_null(item): return NULL
        if not isinstance(container, list): container = [container]
        return any(_cql_equiv(item, c) for c in container)

def _properly_includes(container, item):
    """CQL 'properly includes' operator: list-to-list or element-level."""
    if isinstance(item, list):
        # List-to-list: includes AND strictly larger
        if is_null(container): return NULL
        if not isinstance(container, list): container = [container]
        for elem in item:
            found = any(_cql_equiv(elem, c) for c in container)
            if not found: return False
        return len(container) > len(item)
    else:
        # Element-level (ProperContains):
        # container is null → false (not null)
        if is_null(container): return False
        if not isinstance(container, list): container = [container]
        if len(container) <= 1: return False
        # Check if element is in container using equivalence
        return any(_cql_equiv(item, c) for c in container)


# ═══════════════════════ EVALUATOR ═══════════════════════

class Evaluator(CqlExprVisitor):

    def visitProg(self, ctx):
        return self.visit(ctx.expression())

    # ─── Expression alternatives ───

    def visitTermExpression(self, ctx):
        return self.visit(ctx.expressionTerm())

    def visitQueryExpression(self, ctx):
        return self.visit(ctx.query())

    def visitQuery(self, ctx):
        src = ctx.sourceClause()
        sources = src.aliasedQuerySource()
        if len(sources) == 1:
            qs = sources[0]
            lst = self.visit(qs.querySource())
            if not isinstance(lst, list):
                lst = [lst]
            result = lst
        else:
            lists = []
            aliases = []
            for qs in sources:
                v = self.visit(qs.querySource())
                if not isinstance(v, list): v = [v]
                lists.append(v)
                aliases.append(qs.alias().getText())
            import itertools
            result = []
            for combo in itertools.product(*lists):
                result.append(CqlTuple(dict(zip(aliases, combo))))

        if ctx.sortClause():
            direction = ctx.sortClause().sortDirection().getText()
            reverse = direction in ('desc', 'descending')
            try:
                result = sorted(result, reverse=reverse)
            except TypeError:
                pass

        if ctx.returnClause():
            pass
        return result

    def visitBooleanExpression(self, ctx):
        v = self.visit(ctx.expression())
        tokens = [c.getText() for c in ctx.getChildren()
                  if hasattr(c, 'getText') and c.getText() in ('is', 'not', 'null', 'true', 'false')]
        has_not = 'not' in tokens
        if 'null' in tokens:
            r = is_null(v)
        elif 'true' in tokens:
            r = (v is True)
        elif 'false' in tokens:
            r = (v is False)
        else:
            r = False
        if has_not: r = not r
        return r

    def visitIsTypeExpression(self, ctx):
        v = self.visit(ctx.expression())
        t = ctx.typeSpecifier().getText()
        return _is_type(v, t)

    def visitAsTypeExpression(self, ctx):
        v = self.visit(ctx.expression())
        return v

    def visitCastExpression(self, ctx):
        v = self.visit(ctx.expression())
        t = ctx.typeSpecifier().getText()
        return _cast_to(v, t)

    def visitNotExpression(self, ctx):
        v = self.visit(ctx.expression())
        if is_null(v): return NULL
        return not v

    def visitExistenceExpression(self, ctx):
        v = self.visit(ctx.expression())
        if is_null(v): return False
        if isinstance(v, list): return len(v) > 0
        return True

    def visitBetweenExpression(self, ctx):
        v = self.visit(ctx.expression())
        lo = self.visit(ctx.expressionTerm(0))
        hi = self.visit(ctx.expressionTerm(1))
        if is_null(v) or is_null(lo) or is_null(hi): return NULL
        c1 = _cql_compare(v, lo)
        c2 = _cql_compare(v, hi)
        if is_null(c1) or is_null(c2): return NULL
        return c1 >= 0 and c2 <= 0

    def visitSetExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        op = ctx.getChild(1).getText()
        if is_null(left): left = []
        if is_null(right): right = []
        if not isinstance(left, list): left = [left]
        if not isinstance(right, list): right = [right]
        if op == 'union':
            result = list(left)
            for x in right:
                if not any(_cql_equiv(x, y) for y in result):
                    result.append(x)
            return result
        elif op == 'intersect':
            return [x for x in left if any(_cql_equiv(x, y) for y in right)]
        elif op == 'except':
            return [x for x in left if not any(_cql_equiv(x, y) for y in right)]
        return NULL

    def visitInequalityExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        op = ctx.getChild(1).getText()
        c = _cql_compare(left, right)
        if is_null(c): return NULL
        if op == '<': return c < 0
        if op == '>': return c > 0
        if op == '<=': return c <= 0
        if op == '>=': return c >= 0
        return NULL

    def visitEqualityExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        op = ctx.getChild(1).getText()
        if op == '=': return _cql_eq(left, right)
        if op == '!=':
            r = _cql_eq(left, right)
            if is_null(r): return NULL
            return not r
        if op == '~': return _cql_equiv(left, right)
        if op == '!~': return not _cql_equiv(left, right)
        return NULL

    def visitMembershipExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        op = ctx.getChild(1).getText()
        if op == 'in':
            if is_null(right): return False
            if not isinstance(right, list): right = [right]
            for item in right:
                r = _cql_equiv(left, item)
                if r is True: return True
            return False
        elif op == 'contains':
            if is_null(left): return False
            if not isinstance(left, list): left = [left]
            for item in left:
                r = _cql_equiv(right, item)
                if r is True: return True
            return False
        return NULL

    def visitInclusionExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        # Determine operator: 'includes' or 'included in'
        child_texts = [ctx.getChild(i).getText() for i in range(ctx.getChildCount())]
        if 'included' in child_texts:
            # left included in right → right includes left
            return _list_includes(right, left)
        else:
            # left includes right
            return _list_includes(left, right)

    def visitProperInclusionExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        child_texts = [ctx.getChild(i).getText() for i in range(ctx.getChildCount())]
        if 'included' in child_texts:
            # left properly included in right → right properly includes left
            return _properly_includes(right, left)
        else:
            # left properly includes right
            return _properly_includes(left, right)

    def visitAndExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        if left is False or right is False: return False
        if is_null(left) or is_null(right): return NULL
        return left and right

    def visitOrExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        op = ctx.getChild(1).getText()
        if op == 'xor':
            if is_null(left) or is_null(right): return NULL
            return left != right
        # or
        if left is True or right is True: return True
        if is_null(left) or is_null(right): return NULL
        return left or right

    def visitImpliesExpression(self, ctx):
        left = self.visit(ctx.expression(0))
        right = self.visit(ctx.expression(1))
        if left is False: return True
        if right is True: return True
        if is_null(left):
            if right is True: return True
            if right is False: return NULL
            return NULL
        if left is True:
            if is_null(right): return NULL
            return right
        return NULL

    # ─── ExpressionTerm alternatives ───

    def visitTermExpressionTerm(self, ctx):
        return self.visit(ctx.term())

    def visitInvocationExpressionTerm(self, ctx):
        obj = self.visit(ctx.expressionTerm())
        qi = ctx.qualifiedInvocation()
        if qi.getChildCount() > 0:
            child = qi.getChild(0)
            txt = child.getText()
            if hasattr(child, 'qualifiedFunction') or '(' in txt:
                fname = txt.split('(')[0]
                return _invoke_method(obj, fname)
            if isinstance(obj, CqlTuple):
                return obj.elements.get(txt, NULL)
        return NULL

    def visitIndexedExpressionTerm(self, ctx):
        obj = self.visit(ctx.expressionTerm())
        idx = self.visit(ctx.expression())
        if is_null(obj) or is_null(idx): return NULL
        if isinstance(obj, list):
            i = int(idx) if isinstance(idx, (int, Decimal)) else idx
            if isinstance(i, int) and 0 <= i < len(obj): return obj[i]
            return NULL
        return NULL

    def visitConversionExpressionTerm(self, ctx):
        v = self.visit(ctx.expression())
        t = ctx.typeSpecifier().getText()
        return _convert_to(v, t)

    def visitPolarityExpressionTerm(self, ctx):
        v = self.visit(ctx.expressionTerm())
        op = ctx.getChild(0).getText()
        if is_null(v): return NULL
        if op == '-':
            if isinstance(v, int): return -v
            if isinstance(v, Decimal): return -v
            if isinstance(v, CqlLong): return CqlLong(-v.value)
            if isinstance(v, CqlQuantity): return CqlQuantity(-v.value, v.unit)
        return v

    def visitSuccessorExpressionTerm(self, ctx):
        v = self.visit(ctx.expressionTerm())
        return _successor(v)

    def visitPredecessorExpressionTerm(self, ctx):
        v = self.visit(ctx.expressionTerm())
        return _predecessor(v)

    def visitSingletonFromExpressionTerm(self, ctx):
        v = self.visit(ctx.expressionTerm())
        if is_null(v): return NULL
        if isinstance(v, list):
            if len(v) == 0: return NULL
            if len(v) == 1: return v[0]
            raise ValueError("More than one element in singleton from")
        return v

    def visitTypeExtentExpressionTerm(self, ctx):
        op = ctx.getChild(0).getText()
        t = ctx.namedTypeSpecifier().getText()
        if op == 'minimum': return _type_minimum(t)
        return _type_maximum(t)

    def visitDateTimeComponentExpressionTerm(self, ctx):
        comp = ctx.dateTimeComponent().getText()
        v = self.visit(ctx.expressionTerm())
        if is_null(v): return NULL
        if isinstance(v, CqlDateTime):
            m = {'year': v.year, 'month': v.month, 'day': v.day,
                 'hour': v.hour, 'minute': v.minute, 'second': v.second,
                 'millisecond': v.millisecond}
            r = m.get(comp)
            return r if r is not None else NULL
        if isinstance(v, CqlTime):
            m = {'hour': v.hour, 'minute': v.minute, 'second': v.second,
                 'millisecond': v.millisecond}
            r = m.get(comp)
            return r if r is not None else NULL
        return NULL

    def visitPowerExpressionTerm(self, ctx):
        left = self.visit(ctx.expressionTerm(0))
        right = self.visit(ctx.expressionTerm(1))
        return _power(left, right)

    def visitMultiplicationExpressionTerm(self, ctx):
        left = self.visit(ctx.expressionTerm(0))
        right = self.visit(ctx.expressionTerm(1))
        op = ctx.getChild(1).getText()
        return _multiply(left, right, op)

    def visitAdditionExpressionTerm(self, ctx):
        left = self.visit(ctx.expressionTerm(0))
        right = self.visit(ctx.expressionTerm(1))
        op = ctx.getChild(1).getText()
        return _add(left, right, op)

    def visitIfThenElseExpressionTerm(self, ctx):
        cond = self.visit(ctx.expression(0))
        if cond is True: return self.visit(ctx.expression(1))
        return self.visit(ctx.expression(2))

    def visitCaseExpressionTerm(self, ctx):
        items = ctx.caseExpressionItem()
        exprs = ctx.expression()
        if len(exprs) == 2:
            # Selected case: exprs[0] = comparand, exprs[1] = else
            comparand = self.visit(exprs[0])
            for item in items:
                when_val = self.visit(item.expression(0))
                r = _cql_eq(comparand, when_val)
                if r is True: return self.visit(item.expression(1))
            return self.visit(exprs[1])
        else:
            # Standard case: exprs[0] = else
            for item in items:
                cond = self.visit(item.expression(0))
                if cond is True: return self.visit(item.expression(1))
            return self.visit(exprs[0])

    def visitAggregateExpressionTerm(self, ctx):
        op = ctx.getChild(0).getText()
        v = self.visit(ctx.expression())
        if op == 'distinct':
            if is_null(v): return NULL
            if not isinstance(v, list): return v
            result = []
            for x in v:
                if not any(_cql_equiv(x, y) for y in result):
                    result.append(x)
            return result
        elif op == 'flatten':
            if is_null(v): return NULL
            if not isinstance(v, list): return v
            result = []
            for x in v:
                if isinstance(x, list): result.extend(x)
                else: result.append(x)
            return result
        return v

    # ─── Term alternatives ───

    def visitInvocationTerm(self, ctx):
        return self.visit(ctx.invocation())

    def visitLiteralTerm(self, ctx):
        return self.visit(ctx.literal())

    def visitIntervalSelectorTerm(self, ctx):
        return self.visit(ctx.intervalSelector())

    def visitTupleSelectorTerm(self, ctx):
        return self.visit(ctx.tupleSelector())

    def visitListSelectorTerm(self, ctx):
        return self.visit(ctx.listSelector())

    def visitParenthesizedTerm(self, ctx):
        return self.visit(ctx.expression())

    # ─── Invocation ───

    def visitMemberInvocation(self, ctx):
        return NULL

    def visitFunctionInvocation(self, ctx):
        return self.visit(ctx.fnCall())

    def visitThisInvocation(self, ctx): return NULL
    def visitIndexInvocation(self, ctx): return NULL
    def visitTotalInvocation(self, ctx): return NULL

    def visitFnCall(self, ctx):
        fname = ctx.identifierOrKeyword().getText()
        args = []
        if ctx.paramList():
            args = [self.visit(e) for e in ctx.paramList().expression()]
        return _call_function(fname, args)

    # ─── Literals ───

    def visitBooleanLiteral(self, ctx):
        return ctx.getText() == 'true'

    def visitNullLiteral(self, ctx):
        return NULL

    def visitStringLiteral(self, ctx):
        return _unquote(ctx.getText())

    def visitNumberLiteral(self, ctx):
        txt = ctx.getText()
        if '.' in txt: return Decimal(txt)
        return int(txt)

    def visitLongNumberLiteral(self, ctx):
        return CqlLong(int(ctx.getText()[:-1]))

    def visitDateTimeLiteral(self, ctx):
        return _parse_datetime(ctx.getText())

    def visitDateLiteral(self, ctx):
        return _parse_datetime(ctx.getText())

    def visitTimeLiteral(self, ctx):
        return _parse_time(ctx.getText())

    def visitQuantityLiteral(self, ctx):
        q = ctx.quantity()
        val = Decimal(q.NUMBER().getText())
        u = q.unit().getText()
        return CqlQuantity(val, u)

    # ─── Selectors ───

    def visitIntervalSelector(self, ctx):
        low = self.visit(ctx.expression(0))
        high = self.visit(ctx.expression(1))
        children = [ctx.getChild(i).getText() for i in range(ctx.getChildCount())]
        low_closed = '[' in children[1] if len(children) > 1 else True
        high_closed = ']' in children[-1] if children else True
        return CqlInterval(low, high, low_closed, high_closed)

    def visitTupleSelector(self, ctx):
        elems = ctx.tupleElementSelector()
        if not elems: return CqlTuple({})
        d = {}
        for e in elems:
            name = e.referentialIdentifier().getText()
            val = self.visit(e.expression())
            d[name] = val
        return CqlTuple(d)

    def visitListSelector(self, ctx):
        exprs = ctx.expression()
        if not exprs: return []
        return [self.visit(e) for e in exprs]

    def visitQualifiedMemberInvocation(self, ctx):
        return ctx.getText()

    def visitQualifiedFunctionInvocation(self, ctx):
        return self.visit(ctx.qualifiedFunction())

    def visitQualifiedFunction(self, ctx):
        fname = ctx.identifierOrKeyword().getText()
        args = []
        if ctx.paramList():
            args = [self.visit(e) for e in ctx.paramList().expression()]
        return _call_function(fname, args)


# ═══════════════════════ BUILT-IN FUNCTIONS ═══════════════════════

def _call_function(name, args):
    fn = _FUNCTIONS.get(name)
    if fn: return fn(args)
    return NULL

def _fn_abs(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, int): return abs(v)
    if isinstance(v, Decimal): return abs(v)
    if isinstance(v, CqlLong): return CqlLong(abs(v.value))
    if isinstance(v, CqlQuantity): return CqlQuantity(abs(v.value), v.unit)
    return NULL

def _fn_ceiling(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, int): return v
    if isinstance(v, Decimal):
        import math as _m
        return int(_m.ceil(float(v)))
    return NULL

def _fn_floor(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, int): return v
    if isinstance(v, Decimal):
        import math as _m
        return int(_m.floor(float(v)))
    return NULL

def _fn_truncate(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, int): return v
    if isinstance(v, Decimal): return int(int(v))
    return NULL

def _fn_round(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    prec = int(args[1]) if len(args) > 1 and not is_null(args[1]) else 0
    if isinstance(v, int): v = Decimal(v)
    if isinstance(v, Decimal):
        factor = Decimal(10) ** -prec
        return v.quantize(factor, rounding=ROUND_HALF_UP)
    return NULL

def _fn_exp(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    n = float(v) if isinstance(v, (int, Decimal)) else float(v.value) if isinstance(v, CqlLong) else None
    if n is None: return NULL
    try:
        r = math.exp(n)
        if math.isinf(r): return NULL
        return Decimal(str(r))
    except (OverflowError, ValueError):
        return NULL

def _fn_ln(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    n = float(v) if isinstance(v, (int, Decimal)) else float(v.value) if isinstance(v, CqlLong) else None
    if n is None: return NULL
    if n <= 0: return NULL
    return Decimal(str(math.log(n)))

def _fn_log(args):
    v = args[0] if args else NULL
    base = args[1] if len(args) > 1 else NULL
    if is_null(v) or is_null(base): return NULL
    nv = float(v) if isinstance(v, (int, Decimal)) else None
    nb = float(base) if isinstance(base, (int, Decimal)) else None
    if nv is None or nb is None: return NULL
    if nv <= 0 or nb <= 0 or nb == 1: return NULL
    return Decimal(str(math.log(nv) / math.log(nb)))

def _fn_power(args):
    return _power(args[0] if args else NULL, args[1] if len(args) > 1 else NULL)

def _power(base, exp):
    if is_null(base) or is_null(exp): return NULL
    base, exp = _coerce_arith(base, exp)
    if isinstance(base, int) and isinstance(exp, int):
        if exp < 0: return Decimal(str(base ** exp))
        return base ** exp
    if isinstance(base, Decimal) and isinstance(exp, Decimal):
        try: return Decimal(str(float(base) ** float(exp)))
        except: return NULL
    if isinstance(base, CqlLong) and isinstance(exp, CqlLong):
        return CqlLong(base.value ** exp.value)
    b = float(base) if isinstance(base, (int, Decimal)) else float(base.value) if isinstance(base, CqlLong) else None
    e = float(exp) if isinstance(exp, (int, Decimal)) else float(exp.value) if isinstance(exp, CqlLong) else None
    if b is not None and e is not None:
        try:
            r = b ** e
            if isinstance(base, int) and isinstance(exp, int): return int(r)
            return Decimal(str(r))
        except: return NULL
    return NULL

def _multiply(left, right, op):
    if is_null(left) or is_null(right): return NULL
    left, right = _coerce_arith(left, right)
    if is_null(left): return NULL
    if op == '*':
        if isinstance(left, int) and isinstance(right, int): return left * right
        if isinstance(left, Decimal) and isinstance(right, Decimal): return left * right
        if isinstance(left, CqlLong) and isinstance(right, CqlLong): return CqlLong(left.value * right.value)
        if isinstance(left, CqlQuantity) and isinstance(right, CqlQuantity):
            return CqlQuantity(left.value * right.value, left.unit)
        if isinstance(left, CqlQuantity) and isinstance(right, (int, Decimal)):
            return CqlQuantity(left.value * Decimal(str(right)), left.unit)
        return NULL
    if op == '/':
        r = _to_num(right)
        if r is not None and r == 0: return NULL
        if isinstance(left, int) and isinstance(right, int):
            return Decimal(left) / Decimal(right)
        if isinstance(left, Decimal) and isinstance(right, Decimal):
            if right == 0: return NULL
            return left / right
        if isinstance(left, CqlLong) and isinstance(right, CqlLong):
            if right.value == 0: return NULL
            return Decimal(left.value) / Decimal(right.value)
        if isinstance(left, CqlQuantity) and isinstance(right, CqlQuantity):
            if right.value == 0: return NULL
            return CqlQuantity(left.value / right.value, left.unit)
        if isinstance(left, CqlQuantity) and isinstance(right, (int, Decimal)):
            rv = Decimal(str(right))
            if rv == 0: return NULL
            return CqlQuantity(left.value / rv, left.unit)
        return NULL
    if op == 'div':
        if isinstance(left, int) and isinstance(right, int):
            if right == 0: return NULL
            return int(Decimal(left) / Decimal(right))
        if isinstance(left, Decimal) and isinstance(right, Decimal):
            if right == 0: return NULL
            return Decimal(int(left / right))
        if isinstance(left, CqlLong) and isinstance(right, CqlLong):
            if right.value == 0: return NULL
            return CqlLong(int(Decimal(left.value) / Decimal(right.value)))
        if isinstance(left, CqlQuantity) and isinstance(right, (int, Decimal, CqlQuantity)):
            rv = right.value if isinstance(right, CqlQuantity) else Decimal(str(right))
            if rv == 0: return NULL
            return CqlQuantity(Decimal(int(left.value / rv)), left.unit)
        return NULL
    if op == 'mod':
        if isinstance(left, int) and isinstance(right, int):
            if right == 0: return NULL
            return left % right
        if isinstance(left, Decimal) and isinstance(right, Decimal):
            if right == 0: return NULL
            return left % right
        if isinstance(left, CqlLong) and isinstance(right, CqlLong):
            if right.value == 0: return NULL
            return CqlLong(left.value % right.value)
        return NULL
    return NULL

def _to_num(v):
    if isinstance(v, int): return v
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, CqlLong): return v.value
    return None

def _add(left, right, op):
    if op == '&':
        l = '' if is_null(left) else str(left)
        r = '' if is_null(right) else str(right)
        return l + r
    if is_null(left) or is_null(right): return NULL
    left, right = _coerce_arith(left, right)
    if is_null(left): return NULL
    if isinstance(left, str) and isinstance(right, str):
        if op == '+': return left + right
        if op == '-': return NULL
    if op == '+':
        if isinstance(left, int) and isinstance(right, int): return left + right
        if isinstance(left, Decimal) and isinstance(right, Decimal): return left + right
        if isinstance(left, CqlLong) and isinstance(right, CqlLong): return CqlLong(left.value + right.value)
        if isinstance(left, CqlQuantity) and isinstance(right, CqlQuantity):
            a, b = _align_qty(left, right)
            if a: return CqlQuantity(a.value + b.value, a.unit)
            return CqlQuantity(left.value + right.value, left.unit)
        if isinstance(left, CqlDateTime) and isinstance(right, CqlQuantity):
            return _dt_add(left, right, 1)
        return NULL
    if op == '-':
        if isinstance(left, int) and isinstance(right, int): return left - right
        if isinstance(left, Decimal) and isinstance(right, Decimal): return left - right
        if isinstance(left, CqlLong) and isinstance(right, CqlLong): return CqlLong(left.value - right.value)
        if isinstance(left, CqlQuantity) and isinstance(right, CqlQuantity):
            a, b = _align_qty(left, right)
            if a: return CqlQuantity(a.value - b.value, a.unit)
            return CqlQuantity(left.value - right.value, left.unit)
        if isinstance(left, CqlDateTime) and isinstance(right, CqlQuantity):
            return _dt_add(left, right, -1)
        return NULL
    return NULL

def _dt_add(dt, qty, sign):
    """Add/subtract quantity from datetime."""
    import calendar
    u = _normalize_unit(qty.unit)
    amt = int(qty.value) * sign
    y, mo, d = dt.year or 1, dt.month or 1, dt.day or 1
    h, mi, s, ms = dt.hour or 0, dt.minute or 0, dt.second or 0, dt.millisecond or 0
    if u == 'year':
        y += amt
    elif u == 'month':
        mo += amt
        while mo > 12: y += 1; mo -= 12
        while mo < 1: y -= 1; mo += 12
        max_d = calendar.monthrange(y, mo)[1]
        d = min(d, max_d)
    elif u == 'day':
        try:
            base = pydate(y, mo, d) + timedelta(days=amt)
            y, mo, d = base.year, base.month, base.day
        except: pass
    elif u == 'hour':
        total_ms = ((h * 3600 + mi * 60 + s) * 1000 + ms) + amt * 3600000
        extra_days = total_ms // 86400000
        if total_ms < 0:
            extra_days -= 1
            total_ms -= extra_days * 86400000
        total_ms = total_ms % 86400000
        try:
            base = pydate(y, mo, d) + timedelta(days=extra_days)
            y, mo, d = base.year, base.month, base.day
        except: pass
        h = total_ms // 3600000; total_ms %= 3600000
        mi = total_ms // 60000; total_ms %= 60000
        s = total_ms // 1000; ms = total_ms % 1000
    elif u == 'minute':
        return _dt_add(dt, CqlQuantity(qty.value * 60, "'s'"), sign)
    elif u == 'second':
        return _dt_add(dt, CqlQuantity(qty.value * 1000, "'ms'"), sign)
    elif u == 'millisecond':
        return _dt_add(dt, CqlQuantity(qty.value, "'ms'"), sign)
    elif u == 'week':
        return _dt_add(dt, CqlQuantity(qty.value * 7, "'d'"), sign)
    result = CqlDateTime(y, mo if dt.month is not None else None,
                         d if dt.day is not None else None,
                         h if dt.hour is not None else None,
                         mi if dt.minute is not None else None,
                         s if dt.second is not None else None,
                         ms if dt.millisecond is not None else None,
                         dt.tz)
    return result


def _fn_datetime(args):
    if not args or is_null(args[0]): return NULL
    vals = [int(a) if isinstance(a, (int, Decimal)) and not is_null(a) else None for a in args]
    while len(vals) < 7: vals.append(None)
    return CqlDateTime(*vals[:7])

def _fn_today(args):
    d = pydate.today()
    return CqlDateTime(d.year, d.month, d.day)

def _fn_now(args):
    from datetime import datetime
    n = datetime.now()
    return CqlDateTime(n.year, n.month, n.day, n.hour, n.minute, n.second,
                       n.microsecond // 1000)

def _fn_length(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, list): return len(v)
    if isinstance(v, str): return len(v)
    return NULL

def _fn_first(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, list): return v[0] if v else NULL
    return v

def _fn_last(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, list): return v[-1] if v else NULL
    return v

def _fn_exists(args):
    v = args[0] if args else NULL
    if is_null(v): return False
    if isinstance(v, list): return len(v) > 0
    return True

def _fn_indexof(args):
    lst = args[0] if args else NULL
    elem = args[1] if len(args) > 1 else NULL
    if is_null(lst): return NULL
    if isinstance(lst, list):
        for i, x in enumerate(lst):
            if _cql_equiv(x, elem): return i
        return -1
    return NULL

def _fn_skip(args):
    lst = args[0] if args else NULL
    n = args[1] if len(args) > 1 else NULL
    if is_null(lst) or is_null(n): return NULL
    if isinstance(lst, list): return lst[int(n):]
    return NULL

def _fn_take(args):
    lst = args[0] if args else NULL
    n = args[1] if len(args) > 1 else NULL
    if is_null(lst) or is_null(n): return NULL
    if isinstance(lst, list): return lst[:int(n)]
    return NULL

def _fn_tail(args):
    lst = args[0] if args else NULL
    if is_null(lst): return NULL
    if isinstance(lst, list): return lst[1:] if lst else []
    return NULL

def _fn_flatten(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, list):
        result = []
        for x in v:
            if isinstance(x, list): result.extend(x)
            else: result.append(x)
        return result
    return v

def _fn_coalesce(args):
    if not args: return NULL
    if len(args) == 1 and isinstance(args[0], list):
        for x in args[0]:
            if not is_null(x): return x
        return NULL
    for a in args:
        if isinstance(a, list) and len(a) > 0: return a
        if not is_null(a): return a
    return NULL

def _fn_isnull(args):
    return is_null(args[0]) if args else True

def _fn_istrue(args):
    return args[0] is True if args else False

def _fn_isfalse(args):
    return args[0] is False if args else False

def _fn_tostring(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, int): return str(v)
    if isinstance(v, Decimal):
        s = format(v, 'f')
        if '.' not in s: s += '.0'
        return s
    if isinstance(v, str): return v
    if isinstance(v, CqlQuantity):
        vs = format(v.value, 'f') if isinstance(v.value, Decimal) else str(v.value)
        u = v.unit
        if not u.startswith("'"): u = f"'{u}'"
        return f"{vs} \\{u}\\"
    return str(v)

def _fn_tointeger(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, int): return v
    if isinstance(v, str):
        try: return int(v)
        except: return NULL
    if isinstance(v, Decimal):
        if v == int(v): return int(v)
        return NULL
    if isinstance(v, bool): return 1 if v else 0
    return NULL

def _fn_todecimal(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, Decimal): return v
    if isinstance(v, int): return Decimal(v)
    if isinstance(v, str):
        s = v.strip()
        if s.startswith('+'): s = s[1:]
        try: return Decimal(s)
        except: return NULL
    return NULL

def _fn_toboolean(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, bool): return v
    if isinstance(v, str):
        low = v.lower()
        if low in ('true', 'yes', 'y', '1', 't'): return True
        if low in ('false', 'no', 'n', '0', 'f'): return False
        return NULL
    if isinstance(v, int): return v != 0
    return NULL

def _fn_todatetime(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, CqlDateTime): return v
    if isinstance(v, str):
        return _parse_datetime('@' + v) if not v.startswith('@') else _parse_datetime(v)
    return NULL

def _fn_totime(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, CqlTime): return v
    if isinstance(v, str):
        s = v.lstrip('@')
        return _parse_time('@' + s) if not s.startswith('@') else _parse_time(s)
    return NULL

def _fn_toquantity(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, CqlQuantity): return v
    if isinstance(v, str):
        m = re.match(r"^([\d.]+)\s*'([^']*)'$", v)
        if m: return CqlQuantity(Decimal(m.group(1)), m.group(2))
        return NULL
    if isinstance(v, (int, Decimal)):
        return CqlQuantity(Decimal(str(v)), '1')
    return NULL

def _fn_combine(args):
    lst = args[0] if args else NULL
    sep = args[1] if len(args) > 1 else ''
    if is_null(lst): return NULL
    if isinstance(lst, list):
        parts = []
        for x in lst:
            if is_null(x): return NULL
            parts.append(str(x) if not isinstance(x, str) else x)
        if isinstance(sep, str):
            return sep.join(parts)
        return ''.join(parts)
    return NULL

def _fn_message(args):
    return args[0] if args else NULL

def _fn_slice(args):
    """CQL Slice(list, startIndex, endIndex) function."""
    lst = args[0] if args else NULL
    start = args[1] if len(args) > 1 else NULL
    end = args[2] if len(args) > 2 else NULL

    if is_null(lst): return NULL
    if not isinstance(lst, list): return NULL

    n = len(lst)

    # Handle start index
    if is_null(start):
        s = 0
    else:
        s = int(start) if isinstance(start, (int, Decimal)) else 0
        if s < 0:
            s = max(0, n + s)

    # Handle end index
    if is_null(end):
        e = n
    else:
        e = int(end) if isinstance(end, (int, Decimal)) else n
        if e < 0:
            e = max(0, n + e)

    if s >= n: return []
    if e > n: e = n
    if s >= e: return []

    return lst[s:e]

def _fn_high_boundary(args):
    v = args[0] if args else NULL
    precision = int(args[1]) if len(args) > 1 and not is_null(args[1]) else None
    if is_null(v): return NULL
    if isinstance(v, Decimal):
        if precision is None: precision = 8
        is_neg = v < 0
        v_abs = abs(v)
        s = format(v_abs, 'f')
        if '.' in s:
            int_part, frac_part = s.split('.')
        else:
            int_part = s
            frac_part = ''
        fill = '0' if is_neg else '9'
        if len(frac_part) < precision:
            frac_part = frac_part + fill * (precision - len(frac_part))
        elif len(frac_part) > precision:
            frac_part = frac_part[:precision]
        result = Decimal(int_part + '.' + frac_part)
        return -result if is_neg else result
    if isinstance(v, CqlDateTime):
        _MAX = [9999, 12, 31, 23, 59, 59, 999]
        if precision is None: precision = 17
        fields = list(v._fields())
        for i in range(7):
            if fields[i] is None:
                fields[i] = _MAX[i]
        return CqlDateTime(*fields, tz=v.tz)
    if isinstance(v, CqlTime):
        _MAX = [23, 59, 59, 999]
        fields = list(v._fields())
        for i in range(4):
            if fields[i] is None:
                fields[i] = _MAX[i]
        return CqlTime(*fields)
    return NULL

def _fn_low_boundary(args):
    v = args[0] if args else NULL
    precision = int(args[1]) if len(args) > 1 and not is_null(args[1]) else None
    if is_null(v): return NULL
    if isinstance(v, Decimal):
        if precision is None: precision = 8
        is_neg = v < 0
        v_abs = abs(v)
        s = format(v_abs, 'f')
        if '.' in s:
            int_part, frac_part = s.split('.')
        else:
            int_part = s
            frac_part = ''
        fill = '9' if is_neg else '0'
        if len(frac_part) < precision:
            frac_part = frac_part + fill * (precision - len(frac_part))
        elif len(frac_part) > precision:
            frac_part = frac_part[:precision]
        result = Decimal(int_part + '.' + frac_part)
        return -result if is_neg else result
    if isinstance(v, CqlDateTime):
        _MIN = [1, 1, 1, 0, 0, 0, 0]
        fields = list(v._fields())
        for i in range(7):
            if fields[i] is None:
                fields[i] = _MIN[i]
        return CqlDateTime(*fields, tz=v.tz)
    if isinstance(v, CqlTime):
        _MIN = [0, 0, 0, 0]
        fields = list(v._fields())
        for i in range(4):
            if fields[i] is None:
                fields[i] = _MIN[i]
        return CqlTime(*fields)
    return NULL

def _fn_precision(args):
    v = args[0] if args else NULL
    if is_null(v): return NULL
    if isinstance(v, Decimal):
        s = format(v, 'f')
        if '.' in s:
            return len(s.split('.')[1])
        return 0
    if isinstance(v, CqlDateTime):
        # Return number of digits in the date/time string
        count = 0
        if v.year is not None: count = 4
        if v.month is not None: count = 6
        if v.day is not None: count = 8
        if v.hour is not None: count = 10
        if v.minute is not None: count = 12
        if v.second is not None: count = 14
        if v.millisecond is not None: count = 17
        return count
    if isinstance(v, CqlTime):
        count = 0
        if v.hour is not None: count = 2
        if v.minute is not None: count = 4
        if v.second is not None: count = 6
        if v.millisecond is not None: count = 9
        return count
    return NULL

_FUNCTIONS = {
    'Abs': _fn_abs, 'Ceiling': _fn_ceiling, 'Floor': _fn_floor,
    'Truncate': _fn_truncate, 'Round': _fn_round,
    'Exp': _fn_exp, 'Ln': _fn_ln, 'Log': _fn_log, 'Power': _fn_power,
    'DateTime': _fn_datetime, 'Today': _fn_today, 'Now': _fn_now,
    'TimeOfDay': lambda a: NULL,
    'Length': _fn_length, 'First': _fn_first, 'Last': _fn_last,
    'Exists': _fn_exists, 'IndexOf': _fn_indexof,
    'Skip': _fn_skip, 'Take': _fn_take, 'Tail': _fn_tail,
    'Flatten': _fn_flatten, 'Slice': _fn_slice,
    'Coalesce': _fn_coalesce, 'IsNull': _fn_isnull,
    'IsTrue': _fn_istrue, 'IsFalse': _fn_isfalse,
    'ToString': _fn_tostring, 'ToInteger': _fn_tointeger,
    'ToDecimal': _fn_todecimal, 'ToBoolean': _fn_toboolean,
    'ToDateTime': _fn_todatetime, 'ToTime': _fn_totime,
    'ToQuantity': _fn_toquantity,
    'Combine': _fn_combine, 'Message': _fn_message,
    'HighBoundary': _fn_high_boundary, 'LowBoundary': _fn_low_boundary,
    'Precision': _fn_precision,
    'Date': lambda args: _fn_datetime(args),
}

def _invoke_method(obj, name):
    if name == 'descendents' or name == 'descendants':
        return NULL
    return NULL


# ═══════════════════════ HELPERS ═══════════════════════

def _successor(v):
    if is_null(v): return NULL
    if isinstance(v, int): return v + 1
    if isinstance(v, Decimal):
        step = Decimal(10) ** -8
        return v + step
    if isinstance(v, CqlLong): return CqlLong(v.value + 1)
    if isinstance(v, CqlQuantity): return CqlQuantity(v.value + Decimal(10) ** -8, v.unit)
    if isinstance(v, CqlDateTime):
        return _dt_add(v, CqlQuantity(Decimal(1), 'millisecond'), 1)
    if isinstance(v, CqlTime):
        ms = (v.millisecond or 0) + 1
        s = v.second or 0
        mi = v.minute or 0
        h = v.hour or 0
        if ms >= 1000: ms -= 1000; s += 1
        if s >= 60: s -= 60; mi += 1
        if mi >= 60: mi -= 60; h += 1
        if h >= 24: return NULL
        return CqlTime(h, mi if v.minute is not None else None,
                       s if v.second is not None else None,
                       ms if v.millisecond is not None else None)
    return NULL

def _predecessor(v):
    if is_null(v): return NULL
    if isinstance(v, int): return v - 1
    if isinstance(v, Decimal):
        step = Decimal(10) ** -8
        return v - step
    if isinstance(v, CqlLong): return CqlLong(v.value - 1)
    if isinstance(v, CqlQuantity): return CqlQuantity(v.value - Decimal(10) ** -8, v.unit)
    if isinstance(v, CqlDateTime):
        return _dt_add(v, CqlQuantity(Decimal(1), 'millisecond'), -1)
    if isinstance(v, CqlTime):
        ms = (v.millisecond or 0) - 1
        s = v.second or 0
        mi = v.minute or 0
        h = v.hour or 0
        if ms < 0: ms += 1000; s -= 1
        if s < 0: s += 60; mi -= 1
        if mi < 0: mi += 60; h -= 1
        if h < 0: return NULL
        return CqlTime(h, mi if v.minute is not None else None,
                       s if v.second is not None else None,
                       ms if v.millisecond is not None else None)
    return NULL

def _type_minimum(t):
    t = t.replace('System.', '')
    if t == 'Integer': return -2147483648
    if t == 'Decimal': return Decimal('-99999999999999999999.99999999')
    if t == 'Long': return CqlLong(-9223372036854775808)
    if t == 'DateTime': return CqlDateTime(1, 1, 1, 0, 0, 0, 0)
    if t == 'Time': return CqlTime(0, 0, 0, 0)
    return NULL

def _type_maximum(t):
    t = t.replace('System.', '')
    if t == 'Integer': return 2147483647
    if t == 'Decimal': return Decimal('99999999999999999999.99999999')
    if t == 'Long': return CqlLong(9223372036854775807)
    if t == 'DateTime': return CqlDateTime(9999, 12, 31, 23, 59, 59, 999)
    if t == 'Time': return CqlTime(23, 59, 59, 999)
    return NULL

def _is_type(v, t):
    t = t.replace('System.', '')
    if t == 'Integer': return isinstance(v, int) and not isinstance(v, bool)
    if t == 'Decimal': return isinstance(v, Decimal)
    if t == 'Long': return isinstance(v, CqlLong)
    if t == 'Boolean': return isinstance(v, bool)
    if t == 'String': return isinstance(v, str)
    if t == 'DateTime': return isinstance(v, CqlDateTime)
    if t == 'Time': return isinstance(v, CqlTime)
    if t == 'Quantity': return isinstance(v, CqlQuantity)
    if t == 'Vocabulary' or t == 'ValueSet': return isinstance(v, CqlTuple)
    return False

def _cast_to(v, t):
    return _convert_to(v, t)

def _convert_to(v, t):
    if is_null(v): return NULL
    t = t.replace('System.', '')
    if t == 'Integer': return _fn_tointeger([v])
    if t == 'Decimal': return _fn_todecimal([v])
    if t == 'String': return _fn_tostring([v])
    if t == 'Boolean': return _fn_toboolean([v])
    if t == 'DateTime': return _fn_todatetime([v])
    if t == 'Time': return _fn_totime([v])
    if t == 'Quantity': return _fn_toquantity([v])
    return v

def _unquote(s):
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        s = s[1:-1]
    s = s.replace("\\'", "'").replace('\\"', '"')
    s = s.replace('\\\\', '\\').replace('\\/', '/')
    s = s.replace('\\f', '\f').replace('\\n', '\n')
    s = s.replace('\\r', '\r').replace('\\t', '\t')
    def repl_unicode(m): return chr(int(m.group(1), 16))
    s = re.sub(r'\\u([0-9a-fA-F]{4})', repl_unicode, s)
    return s

def _parse_datetime(s):
    s = s.lstrip('@')
    tz = None
    tz_match = re.search(r'([+-]\d{2}:\d{2}|Z)$', s)
    if tz_match:
        tz_str = tz_match.group(1)
        s = s[:tz_match.start()]
        tz = '+00:00' if tz_str == 'Z' else tz_str
    if 'T' in s:
        date_part, time_part = s.split('T', 1)
    else:
        date_part = s
        time_part = ''
    dp = date_part.split('-')
    year = int(dp[0]) if len(dp) > 0 and dp[0] else None
    month = int(dp[1]) if len(dp) > 1 else None
    day = int(dp[2]) if len(dp) > 2 else None
    hour = minute = second = ms = None
    if time_part:
        tp = time_part.split(':')
        hour = int(tp[0]) if len(tp) > 0 and tp[0] else None
        minute = int(tp[1]) if len(tp) > 1 else None
        if len(tp) > 2:
            sec_parts = tp[2].split('.')
            second = int(sec_parts[0])
            if len(sec_parts) > 1:
                frac = sec_parts[1][:3].ljust(3, '0')
                ms = int(frac)
    return CqlDateTime(year, month, day, hour, minute, second, ms, tz)

def _parse_time(s):
    s = s.lstrip('@').lstrip('T')
    tz_match = re.search(r'([+-]\d{2}:\d{2}|Z)$', s)
    if tz_match:
        s = s[:tz_match.start()]
    tp = s.split(':')
    hour = int(tp[0]) if len(tp) > 0 and tp[0] else None
    minute = int(tp[1]) if len(tp) > 1 else None
    second = ms = None
    if len(tp) > 2:
        sec_parts = tp[2].split('.')
        second = int(sec_parts[0])
        if len(sec_parts) > 1:
            frac = sec_parts[1][:3].ljust(3, '0')
            ms = int(frac)
    return CqlTime(hour, minute, second, ms)


# ═══════════════════════ XML FIXTURE PARSER ═══════════════════════

NS = {'t': 'http://hl7.org/fhirpath/tests'}
SKIP_CAPS = {'ucum-unit-conversion-support', 'unit-conversion-support'}

def parse_fixture(xml_path):
    tree = ElementTree.parse(xml_path)
    root = tree.getroot()
    tests = []
    for group in root.findall('.//t:group', NS):
        group_name = group.get('name', '')
        group_caps = {c.get('code') for c in group.findall('t:capability', NS)}
        skip_group = bool(group_caps & SKIP_CAPS)
        for test in group.findall('t:test', NS):
            test_name = test.get('name', '')
            expr_elem = test.find('t:expression', NS)
            if expr_elem is None: continue
            if expr_elem.get('invalid') is not None: continue
            test_caps = {c.get('code') for c in test.findall('t:capability', NS)}
            if test_caps & SKIP_CAPS: continue
            if skip_group and not test_caps: continue
            expr_text = (expr_elem.text or '').strip()
            if not expr_text: continue
            output_elem = test.find('t:output', NS)
            if output_elem is None: continue
            expected = (output_elem.text or '').strip()
            tests.append({
                'name': test_name,
                'group': group_name,
                'expression': expr_text,
                'expected': expected,
            })
    return tests


# ═══════════════════════ COMPARISON ═══════════════════════

def normalize_output(s):
    s = s.strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*\{\s*', '{', s)
    s = re.sub(r'\s*\}\s*', '}', s)
    s = re.sub(r'\s*\[\s*', '[', s)
    s = re.sub(r'\s*\]\s*', ']', s)
    s = re.sub(r'\s*\(\s*', '(', s)
    s = re.sub(r'\s*\)\s*', ')', s)
    s = re.sub(r',\s*', ', ', s)
    s = re.sub(r':\s*', ': ', s)
    s = re.sub(r"(\d)\s+'", r"\1'", s)
    s = re.sub(r"(\d)\s+\[", r"\1 [", s)
    return s


def outputs_match(actual, expected):
    return normalize_output(actual) == normalize_output(expected)


# ═══════════════════════ EVALUATE EXPRESSION ═══════════════════════

def evaluate_expression(expr_text):
    try:
        input_stream = InputStream(expr_text)
        lexer = CqlExprLexer(input_stream)
        lexer.removeErrorListeners()
        stream = CommonTokenStream(lexer)
        parser = CqlExprParser(stream)
        parser.removeErrorListeners()
        tree = parser.prog()
        evaluator = Evaluator()
        result = evaluator.visit(tree)
        return format_cql(result)
    except Exception as e:
        return f'ERROR: {e}'


# ═══════════════════════ CLI ═══════════════════════

def process_fixture(xml_path):
    fixture_tests = parse_fixture(xml_path)
    results = []
    for t in fixture_tests:
        actual = evaluate_expression(t['expression'])
        passed = outputs_match(actual, t['expected'])
        results.append({
            'name': t['name'],
            'group': t['group'],
            'expression': t['expression'],
            'expected': t['expected'],
            'actual': actual,
            'pass': passed,
        })
    total = len(results)
    passed = sum(1 for r in results if r['pass'])
    return {
        'file': os.path.basename(xml_path),
        'tests': results,
        'summary': {'total': total, 'passed': passed, 'failed': total - passed},
    }


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: cql_runner.py <fixture.xml> | --batch", file=sys.stderr)
        sys.exit(1)

    if args[0] == '--batch':
        fixtures = sorted(glob.glob('/app/fixtures/*.xml'))
        results = [process_fixture(f) for f in fixtures]
        print(json.dumps(results, indent=None))
    else:
        result = process_fixture(args[0])
        print(json.dumps(result, indent=None))


if __name__ == '__main__':
    main()
