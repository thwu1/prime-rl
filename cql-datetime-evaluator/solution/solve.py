#!/usr/bin/env python3
"""CQL Conformance Test Runner - Reference Solution.

"""

import os
import re
import glob
import subprocess
import calendar
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date as pydate

# ======================== CQL Value Types ========================

PRECISION_ORDER = ['year', 'month', 'day', 'hour', 'minute', 'second', 'millisecond']


def prec_index(p):
    return PRECISION_ORDER.index(p)


class CqlNull:
    pass


class CqlBoolean:
    def __init__(self, value):
        self.value = value


class CqlInteger:
    def __init__(self, value):
        self.value = int(value)


class CqlInterval:
    def __init__(self, low, high):
        self.low = low
        self.high = high


class CqlDateTime:
    def __init__(self, year, month=None, day=None, hour=None, minute=None,
                 second=None, ms=None, tz=None, is_date=False):
        self.year = int(year)
        self.month = int(month) if month is not None else None
        self.day = int(day) if day is not None else None
        self.hour = int(hour) if hour is not None else None
        self.minute = int(minute) if minute is not None else None
        self.second = int(second) if second is not None else None
        self.ms = int(ms) if ms is not None else None
        self.tz = float(tz) if tz is not None else None
        self.is_date = is_date

    @property
    def precision(self):
        if self.ms is not None: return 'millisecond'
        if self.second is not None: return 'second'
        if self.minute is not None: return 'minute'
        if self.hour is not None: return 'hour'
        if self.day is not None: return 'day'
        if self.month is not None: return 'month'
        return 'year'

    def filled_low(self):
        return CqlDateTime(
            self.year, self.month or 1, self.day or 1,
            self.hour or 0, self.minute or 0, self.second or 0,
            self.ms or 0, self.tz, self.is_date)

    def filled_high(self):
        m = self.month or 12
        d = self.day if self.day is not None else calendar.monthrange(self.year, m)[1]
        return CqlDateTime(
            self.year, m, d,
            self.hour if self.hour is not None else 23,
            self.minute if self.minute is not None else 59,
            self.second if self.second is not None else 59,
            self.ms if self.ms is not None else 999,
            self.tz, self.is_date)

    def duration_bound_high(self):
        m = self.month if self.month is not None else 12
        d = self.day if self.day is not None else calendar.monthrange(self.year, m)[1]
        return CqlDateTime(
            self.year, m, d,
            self.hour if self.hour is not None else 0,
            self.minute if self.minute is not None else 0,
            self.second if self.second is not None else 0,
            self.ms if self.ms is not None else 0,
            self.tz, self.is_date)

    def to_utc_ms(self):
        f = self.filled_low()
        py = datetime(f.year, f.month, f.day, f.hour, f.minute, f.second, f.ms * 1000)
        if f.tz is not None:
            py = py - timedelta(hours=f.tz)
        epoch = datetime(1, 1, 1)
        return int((py - epoch).total_seconds() * 1000)

    def to_ordinal(self):
        f = self.filled_low()
        return pydate(f.year, f.month, f.day).toordinal()

    def normalize_to_utc(self):
        if self.tz is None:
            return self.filled_low()
        f = self.filled_low()
        py = datetime(f.year, f.month, f.day, f.hour, f.minute, f.second, f.ms * 1000)
        py = py - timedelta(hours=f.tz)
        return CqlDateTime(py.year, py.month, py.day, py.hour, py.minute,
                           py.second, py.microsecond // 1000, None, self.is_date)

    def component_tuple(self, up_to_precision):
        n = self.normalize_to_utc() if self.tz is not None else self.filled_low()
        comps = [n.year, n.month, n.day, n.hour, n.minute, n.second, n.ms]
        idx = prec_index(up_to_precision)
        return tuple(comps[:idx + 1])


class CqlTime:
    def __init__(self, hour, minute=None, second=None, ms=None):
        self.hour = int(hour)
        self.minute = int(minute) if minute is not None else None
        self.second = int(second) if second is not None else None
        self.ms = int(ms) if ms is not None else None

    @property
    def precision(self):
        if self.ms is not None: return 'millisecond'
        if self.second is not None: return 'second'
        if self.minute is not None: return 'minute'
        return 'hour'

    def filled_low(self):
        return CqlTime(self.hour, self.minute or 0, self.second or 0, self.ms or 0)

    def filled_high(self):
        return CqlTime(self.hour,
                       self.minute if self.minute is not None else 59,
                       self.second if self.second is not None else 59,
                       self.ms if self.ms is not None else 999)

    def to_total_ms(self):
        f = self.filled_low()
        return f.hour * 3600000 + f.minute * 60000 + f.second * 1000 + f.ms


# ======================== Tokenizer ========================

def tokenize(expr):
    tokens = []
    pos = 0
    while pos < len(expr):
        if expr[pos].isspace():
            pos += 1
            continue
        if expr[pos] == '@' and pos + 1 < len(expr) and expr[pos + 1] == 'T':
            m = re.match(r'@T\d{2}(?::\d{2}(?::\d{2}(?:\.\d{3})?)?)?', expr[pos:])
            if m:
                tokens.append(('TIME_LIT', m.group()))
                pos += m.end()
                continue
        if expr[pos] == '@' and pos + 1 < len(expr) and expr[pos + 1].isdigit():
            m = re.match(
                r'@(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T(\d{2})(?::(\d{2})(?::(\d{2})(?:\.(\d{3}))?)?)?(?:([+-]\d{2}:\d{2}))?)?)?)?T?',
                expr[pos:]
            )
            if m:
                tokens.append(('DT_LIT', m.group()))
                pos += m.end()
                continue
        if expr[pos].isdigit():
            m = re.match(r'\d+(?:\.\d+)?', expr[pos:])
            if m:
                tokens.append(('NUM', m.group()))
                pos += m.end()
                continue
        if expr[pos:pos+2] in ('>=', '<='):
            tokens.append(('OP', expr[pos:pos+2]))
            pos += 2
            continue
        if expr[pos] in '=><':
            tokens.append(('OP', expr[pos]))
            pos += 1
            continue
        if expr[pos] == '+':
            tokens.append(('PLUS', '+'))
            pos += 1
            continue
        if expr[pos] == '-':
            if pos + 1 < len(expr) and expr[pos+1].isdigit():
                if tokens and tokens[-1][0] in ('NUM', 'RPAREN', 'DT_LIT', 'TIME_LIT', 'WORD'):
                    tokens.append(('MINUS', '-'))
                    pos += 1
                    continue
                m = re.match(r'-\d+(?:\.\d+)?', expr[pos:])
                if m:
                    tokens.append(('NUM', m.group()))
                    pos += m.end()
                    continue
            tokens.append(('MINUS', '-'))
            pos += 1
            continue
        if expr[pos] == '(':
            tokens.append(('LPAREN', '('))
            pos += 1
            continue
        if expr[pos] == ')':
            tokens.append(('RPAREN', ')'))
            pos += 1
            continue
        if expr[pos] == ',':
            tokens.append(('COMMA', ','))
            pos += 1
            continue
        if expr[pos].isalpha() or expr[pos] == '_':
            m = re.match(r'[A-Za-z_][A-Za-z_0-9]*', expr[pos:])
            if m:
                tokens.append(('WORD', m.group()))
                pos += m.end()
                continue
        raise ValueError(f"Unexpected character '{expr[pos]}' at position {pos}")
    return tokens


# ======================== Parser ========================

UNIT_KEYWORDS = {
    'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds',
    'year', 'month', 'week', 'day', 'hour', 'minute', 'second', 'millisecond'
}


def normalize_unit(u):
    if u.endswith('s') and u[:-1] in UNIT_KEYWORDS:
        return u[:-1]
    return u


class AstNode:
    pass

class DateTimeConstructor(AstNode):
    def __init__(self, args, is_date=False):
        self.args = args
        self.is_date = is_date

class TimeConstructor(AstNode):
    def __init__(self, args):
        self.args = args

class DateTimeLiteral(AstNode):
    def __init__(self, text):
        self.text = text

class TimeLiteral(AstNode):
    def __init__(self, text):
        self.text = text

class NumberLiteral(AstNode):
    def __init__(self, value):
        self.value = value

class BoolLiteral(AstNode):
    def __init__(self, value):
        self.value = value

class NullLiteral(AstNode):
    pass

class ArithOp(AstNode):
    def __init__(self, op, left, amount, unit):
        self.op = op
        self.left = left
        self.amount = amount
        self.unit = unit

class DurationBetween(AstNode):
    def __init__(self, unit, a, b):
        self.unit = unit
        self.a = a
        self.b = b

class DifferenceIn(AstNode):
    def __init__(self, unit, a, b):
        self.unit = unit
        self.a = a
        self.b = b

class SameAs(AstNode):
    def __init__(self, precision, a, b):
        self.precision = precision
        self.a = a
        self.b = b

class AfterBefore(AstNode):
    def __init__(self, direction, precision, a, b):
        self.direction = direction
        self.precision = precision
        self.a = a
        self.b = b

class Comparison(AstNode):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, ttype=None, tval=None):
        tok = self.advance()
        if ttype and tok[0] != ttype:
            raise ValueError(f"Expected {ttype}, got {tok}")
        if tval and tok[1] != tval:
            raise ValueError(f"Expected '{tval}', got '{tok[1]}'")
        return tok

    def parse(self):
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_timing()
        p = self.peek()
        if p and p[0] == 'OP':
            op = self.advance()[1]
            right = self.parse_timing()
            return Comparison(op, left, right)
        return left

    def parse_timing(self):
        left = self.parse_additive()
        p = self.peek()
        if p and p[0] == 'WORD':
            if p[1] == 'same':
                self.advance()
                precision = normalize_unit(self.advance()[1])
                self.expect(tval='as')
                right = self.parse_additive()
                return SameAs(precision, left, right)
            elif p[1] == 'after':
                self.advance()
                precision = normalize_unit(self.advance()[1])
                self.expect(tval='of')
                right = self.parse_additive()
                return AfterBefore('after', precision, left, right)
            elif p[1] == 'before':
                self.advance()
                precision = normalize_unit(self.advance()[1])
                self.expect(tval='of')
                right = self.parse_additive()
                return AfterBefore('before', precision, left, right)
        return left

    def parse_additive(self):
        left = self.parse_primary()
        while True:
            p = self.peek()
            if p and p[0] in ('PLUS', 'MINUS'):
                op = self.advance()[1]
                amount_tok = self.advance()
                amount = float(amount_tok[1]) if '.' in amount_tok[1] else int(amount_tok[1])
                unit_tok = self.advance()
                unit = normalize_unit(unit_tok[1])
                left = ArithOp(op, left, amount, unit)
            else:
                break
        return left

    def parse_primary(self):
        p = self.peek()
        if not p:
            raise ValueError("Unexpected end of expression")

        if p[0] == 'WORD' and p[1] in UNIT_KEYWORDS:
            if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][1] == 'between':
                unit = normalize_unit(self.advance()[1])
                self.expect(tval='between')
                a = self.parse_additive()
                self.expect(tval='and')
                b = self.parse_additive()
                return DurationBetween(unit, a, b)

        if p[0] == 'WORD' and p[1] == 'difference':
            self.advance()
            self.expect(tval='in')
            unit = normalize_unit(self.advance()[1])
            self.expect(tval='between')
            a = self.parse_additive()
            self.expect(tval='and')
            b = self.parse_additive()
            return DifferenceIn(unit, a, b)

        if p[0] == 'WORD' and p[1] == 'DateTime':
            self.advance()
            self.expect(ttype='LPAREN')
            args = self._parse_arg_list()
            self.expect(ttype='RPAREN')
            return DateTimeConstructor(args, is_date=False)

        if p[0] == 'WORD' and p[1] == 'Date':
            self.advance()
            self.expect(ttype='LPAREN')
            args = self._parse_arg_list()
            self.expect(ttype='RPAREN')
            return DateTimeConstructor(args, is_date=True)

        if p[0] == 'WORD' and p[1] == 'Time':
            self.advance()
            self.expect(ttype='LPAREN')
            args = self._parse_arg_list()
            self.expect(ttype='RPAREN')
            return TimeConstructor(args)

        if p[0] == 'WORD' and p[1] == 'true':
            self.advance()
            return BoolLiteral(True)
        if p[0] == 'WORD' and p[1] == 'false':
            self.advance()
            return BoolLiteral(False)
        if p[0] == 'WORD' and p[1] == 'null':
            self.advance()
            return NullLiteral()

        if p[0] == 'DT_LIT':
            self.advance()
            return DateTimeLiteral(p[1])

        if p[0] == 'TIME_LIT':
            self.advance()
            return TimeLiteral(p[1])

        if p[0] == 'NUM':
            self.advance()
            return NumberLiteral(float(p[1]) if '.' in p[1] else int(p[1]))

        if p[0] == 'LPAREN':
            self.advance()
            inner = self.parse_comparison()
            self.expect(ttype='RPAREN')
            return inner

        raise ValueError(f"Unexpected token: {p}")

    def _parse_arg_list(self):
        args = []
        while True:
            p = self.peek()
            if p and p[0] == 'RPAREN':
                break
            if args:
                self.expect(ttype='COMMA')
            p = self.peek()
            if p[0] == 'MINUS':
                self.advance()
                num_tok = self.advance()
                val = float(num_tok[1]) if '.' in num_tok[1] else int(num_tok[1])
                args.append(-val)
            else:
                num_tok = self.advance()
                val = float(num_tok[1]) if '.' in num_tok[1] else int(num_tok[1])
                args.append(val)
        return args


# ======================== Literal Parsing ========================

def parse_dt_literal(text):
    raw = text[1:]
    tz = None
    tz_match = re.search(r'([+-])(\d{2}):(\d{2})$', raw)
    if tz_match:
        sign = 1 if tz_match.group(1) == '+' else -1
        tz = sign * (int(tz_match.group(2)) + int(tz_match.group(3)) / 60.0)
        raw = raw[:tz_match.start()]

    is_date = 'T' not in raw

    if 'T' in raw:
        date_part, time_part = raw.split('T', 1)
    else:
        date_part = raw
        time_part = ''

    date_comps = date_part.split('-') if date_part else []
    year = int(date_comps[0]) if len(date_comps) > 0 else None
    month = int(date_comps[1]) if len(date_comps) > 1 else None
    day = int(date_comps[2]) if len(date_comps) > 2 else None

    hour = minute = second = ms = None
    if time_part:
        time_segs = time_part.split(':')
        if len(time_segs) > 0 and time_segs[0]:
            hour = int(time_segs[0])
        if len(time_segs) > 1:
            minute = int(time_segs[1])
        if len(time_segs) > 2:
            sec_part = time_segs[2]
            if '.' in sec_part:
                sec_str, ms_str = sec_part.split('.')
                second = int(sec_str)
                ms = int(ms_str)
            else:
                second = int(sec_part)

    return CqlDateTime(year, month, day, hour, minute, second, ms, tz, is_date)


def parse_time_literal(text):
    raw = text[2:]
    parts = raw.split(':')
    hour = int(parts[0])
    minute = second = ms = None
    if len(parts) > 1:
        minute = int(parts[1])
    if len(parts) > 2:
        sec_part = parts[2]
        if '.' in sec_part:
            sec_str, ms_str = sec_part.split('.')
            second = int(sec_str)
            ms = int(ms_str)
        else:
            second = int(sec_part)
    return CqlTime(hour, minute, second, ms)


# ======================== Evaluator ========================

def evaluate(node):
    if isinstance(node, DateTimeConstructor):
        args = node.args
        if node.is_date:
            return CqlDateTime(
                args[0],
                args[1] if len(args) > 1 else None,
                args[2] if len(args) > 2 else None,
                is_date=True
            )
        else:
            return CqlDateTime(
                args[0],
                args[1] if len(args) > 1 else None,
                args[2] if len(args) > 2 else None,
                args[3] if len(args) > 3 else None,
                args[4] if len(args) > 4 else None,
                args[5] if len(args) > 5 else None,
                args[6] if len(args) > 6 else None,
                args[7] if len(args) > 7 else None,
            )
    if isinstance(node, TimeConstructor):
        args = node.args
        return CqlTime(
            args[0],
            args[1] if len(args) > 1 else None,
            args[2] if len(args) > 2 else None,
            args[3] if len(args) > 3 else None,
        )
    if isinstance(node, DateTimeLiteral):
        return parse_dt_literal(node.text)
    if isinstance(node, TimeLiteral):
        return parse_time_literal(node.text)
    if isinstance(node, NumberLiteral):
        if isinstance(node.value, float):
            return CqlInteger(int(node.value))
        return CqlInteger(node.value)
    if isinstance(node, BoolLiteral):
        return CqlBoolean(node.value)
    if isinstance(node, NullLiteral):
        return CqlNull()
    if isinstance(node, ArithOp):
        return eval_arith(node)
    if isinstance(node, DurationBetween):
        return eval_duration_between(node)
    if isinstance(node, DifferenceIn):
        return eval_difference_in(node)
    if isinstance(node, SameAs):
        return eval_same_as(node)
    if isinstance(node, AfterBefore):
        return eval_after_before(node)
    if isinstance(node, Comparison):
        return eval_comparison(node)
    raise ValueError(f"Unknown node type: {type(node)}")


# ======================== DateTime Arithmetic ========================

def add_to_datetime(dt, amount, unit):
    amount = int(amount)
    f = dt.filled_low()
    y, m, d = f.year, f.month, f.day
    h, mi, s, ms = f.hour, f.minute, f.second, f.ms

    if unit == 'year':
        y += amount
        max_d = calendar.monthrange(y, m)[1]
        if d > max_d:
            d = max_d
    elif unit == 'month':
        total_months = (y * 12 + (m - 1)) + amount
        y = total_months // 12
        m = (total_months % 12) + 1
        max_d = calendar.monthrange(y, m)[1]
        if d > max_d:
            d = max_d
    elif unit == 'week':
        py_dt = datetime(y, m, d, h, mi, s, ms * 1000)
        py_dt += timedelta(weeks=amount)
        y, m, d = py_dt.year, py_dt.month, py_dt.day
        h, mi, s = py_dt.hour, py_dt.minute, py_dt.second
        ms = py_dt.microsecond // 1000
    elif unit == 'day':
        py_dt = datetime(y, m, d, h, mi, s, ms * 1000)
        py_dt += timedelta(days=amount)
        y, m, d = py_dt.year, py_dt.month, py_dt.day
        h, mi, s = py_dt.hour, py_dt.minute, py_dt.second
        ms = py_dt.microsecond // 1000
    elif unit == 'hour':
        py_dt = datetime(y, m, d, h, mi, s, ms * 1000)
        py_dt += timedelta(hours=amount)
        y, m, d = py_dt.year, py_dt.month, py_dt.day
        h, mi, s = py_dt.hour, py_dt.minute, py_dt.second
        ms = py_dt.microsecond // 1000
    elif unit == 'minute':
        py_dt = datetime(y, m, d, h, mi, s, ms * 1000)
        py_dt += timedelta(minutes=amount)
        y, m, d = py_dt.year, py_dt.month, py_dt.day
        h, mi, s = py_dt.hour, py_dt.minute, py_dt.second
        ms = py_dt.microsecond // 1000
    elif unit == 'second':
        py_dt = datetime(y, m, d, h, mi, s, ms * 1000)
        py_dt += timedelta(seconds=amount)
        y, m, d = py_dt.year, py_dt.month, py_dt.day
        h, mi, s = py_dt.hour, py_dt.minute, py_dt.second
        ms = py_dt.microsecond // 1000
    elif unit == 'millisecond':
        py_dt = datetime(y, m, d, h, mi, s, ms * 1000)
        py_dt += timedelta(milliseconds=amount)
        y, m, d = py_dt.year, py_dt.month, py_dt.day
        h, mi, s = py_dt.hour, py_dt.minute, py_dt.second
        ms = py_dt.microsecond // 1000

    prec = dt.precision
    result = CqlDateTime(y, is_date=dt.is_date)
    if prec_index(prec) >= prec_index('month'):
        result.month = m
    if prec_index(prec) >= prec_index('day'):
        result.day = d
    if prec_index(prec) >= prec_index('hour') and not dt.is_date:
        result.hour = h
    if prec_index(prec) >= prec_index('minute') and not dt.is_date:
        result.minute = mi
    if prec_index(prec) >= prec_index('second') and not dt.is_date:
        result.second = s
    if prec_index(prec) >= prec_index('millisecond') and not dt.is_date:
        result.ms = ms
    return result


def add_to_time(t, amount, unit):
    amount = int(amount)
    f = t.filled_low()
    total_ms = f.hour * 3600000 + f.minute * 60000 + f.second * 1000 + f.ms

    if unit == 'hour':
        total_ms += amount * 3600000
    elif unit == 'minute':
        total_ms += amount * 60000
    elif unit == 'second':
        total_ms += amount * 1000
    elif unit == 'millisecond':
        total_ms += amount

    total_ms = total_ms % (24 * 3600000)
    h = total_ms // 3600000
    rem = total_ms % 3600000
    mi = rem // 60000
    rem = rem % 60000
    s = rem // 1000
    ms_val = rem % 1000

    prec = t.precision
    result = CqlTime(h)
    if prec_index(prec) >= prec_index('minute'):
        result.minute = mi
    if prec_index(prec) >= prec_index('second'):
        result.second = s
    if prec_index(prec) >= prec_index('millisecond'):
        result.ms = ms_val
    return result


def eval_arith(node):
    left = evaluate(node.left)
    if isinstance(left, CqlDateTime):
        return add_to_datetime(left, node.amount if node.op == '+' else -node.amount, node.unit)
    elif isinstance(left, CqlTime):
        return add_to_time(left, node.amount if node.op == '+' else -node.amount, node.unit)
    raise ValueError(f"Cannot do arithmetic on {type(left)}")


# ======================== Duration Between ========================

def _duration_years(a, b):
    a_f, b_f = a.filled_low(), b.filled_low()
    diff = b_f.year - a_f.year
    a_sub = (a_f.month, a_f.day, a_f.hour, a_f.minute, a_f.second, a_f.ms)
    b_sub = (b_f.month, b_f.day, b_f.hour, b_f.minute, b_f.second, b_f.ms)
    if diff > 0 and b_sub < a_sub:
        diff -= 1
    elif diff < 0 and b_sub > a_sub:
        diff += 1
    return diff


def _duration_months(a, b):
    a_f, b_f = a.filled_low(), b.filled_low()
    diff = (b_f.year - a_f.year) * 12 + (b_f.month - a_f.month)
    a_sub = (a_f.day, a_f.hour, a_f.minute, a_f.second, a_f.ms)
    b_sub = (b_f.day, b_f.hour, b_f.minute, b_f.second, b_f.ms)
    if diff > 0 and b_sub < a_sub:
        diff -= 1
    elif diff < 0 and b_sub > a_sub:
        diff += 1
    return diff


def eval_duration_between(node):
    a = evaluate(node.a)
    b = evaluate(node.b)
    unit = node.unit
    if isinstance(a, (CqlDateTime, CqlTime)) and isinstance(b, (CqlDateTime, CqlTime)):
        return _compute_duration_with_uncertainty(a, b, unit)
    raise ValueError(f"Cannot compute duration between {type(a)} and {type(b)}")


def _compute_duration_with_uncertainty(a, b, unit):
    if isinstance(a, CqlTime) and isinstance(b, CqlTime):
        divisors = {'hour': 3600000, 'minute': 60000, 'second': 1000, 'millisecond': 1}
        diff_ms = b.filled_low().to_total_ms() - a.filled_low().to_total_ms()
        return CqlInteger(int(diff_ms / divisors[unit]))

    if unit in ('year', 'month'):
        return _duration_calendar_with_uncertainty(a, b, unit)

    if unit in ('day', 'week'):
        if (prec_index(a.precision) > prec_index('day') and
                prec_index(b.precision) > prec_index('day')):
            a_ms = a.filled_low().to_utc_ms()
            b_ms = b.filled_low().to_utc_ms()
            diff_ms = b_ms - a_ms
            divisor = (7 * 24 * 3600 * 1000) if unit == 'week' else (24 * 3600 * 1000)
            return CqlInteger(int(diff_ms / divisor))
        return _duration_date_with_uncertainty(a, b, unit)

    a_ms = a.filled_low().to_utc_ms()
    b_ms = b.filled_low().to_utc_ms()
    diff_ms = b_ms - a_ms
    divisors = {'hour': 3600000, 'minute': 60000, 'second': 1000, 'millisecond': 1}
    return CqlInteger(int(diff_ms / divisors[unit]))


def _duration_calendar_with_uncertainty(a, b, unit):
    func = _duration_years if unit == 'year' else _duration_months
    vals = set()
    for a_bound in [a.filled_low(), a.duration_bound_high()]:
        for b_bound in [b.filled_low(), b.duration_bound_high()]:
            vals.add(func(a_bound, b_bound))
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return CqlInteger(lo)
    return CqlInterval(lo, hi)


def _duration_date_with_uncertainty(a, b, unit):
    a_bounds = set()
    b_bounds = set()
    for dt_val, bounds_set in [(a, a_bounds), (b, b_bounds)]:
        lo = dt_val.filled_low()
        hi = dt_val.duration_bound_high()
        bounds_set.add(pydate(lo.year, lo.month, lo.day).toordinal())
        bounds_set.add(pydate(hi.year, hi.month, hi.day).toordinal())
    vals = set()
    for a_ord in a_bounds:
        for b_ord in b_bounds:
            diff = b_ord - a_ord
            if unit == 'week':
                vals.add(int(diff / 7))
            else:
                vals.add(diff)
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return CqlInteger(lo)
    return CqlInterval(lo, hi)


# ======================== Difference In ========================

def eval_difference_in(node):
    a = evaluate(node.a)
    b = evaluate(node.b)
    unit = node.unit
    if isinstance(a, CqlTime) and isinstance(b, CqlTime):
        return _diff_time(a, b, unit)
    if isinstance(a, CqlDateTime) and isinstance(b, CqlDateTime):
        return _diff_datetime(a, b, unit)
    raise ValueError(f"Cannot compute difference between {type(a)} and {type(b)}")


def _a_ord_ms(dt):
    py = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.ms * 1000)
    epoch = datetime(1, 1, 1)
    return int((py - epoch).total_seconds() * 1000)


def _diff_datetime(a, b, unit):
    a_n = a.normalize_to_utc() if a.tz is not None else a.filled_low()
    b_n = b.normalize_to_utc() if b.tz is not None else b.filled_low()

    if unit == 'year':
        return CqlInteger(b_n.year - a_n.year)
    if unit == 'month':
        return CqlInteger((b_n.year - a_n.year) * 12 + (b_n.month - a_n.month))
    if unit == 'day':
        a_ord = pydate(a_n.year, a_n.month, a_n.day).toordinal()
        b_ord = pydate(b_n.year, b_n.month, b_n.day).toordinal()
        return CqlInteger(b_ord - a_ord)
    if unit == 'week':
        a_ord = pydate(a_n.year, a_n.month, a_n.day).toordinal()
        b_ord = pydate(b_n.year, b_n.month, b_n.day).toordinal()
        a_dow = (pydate(a_n.year, a_n.month, a_n.day).isoweekday()) % 7
        b_dow = (pydate(b_n.year, b_n.month, b_n.day).isoweekday()) % 7
        a_sunday = a_ord - a_dow
        b_sunday = b_ord - b_dow
        return CqlInteger((b_sunday - a_sunday) // 7)
    if unit == 'hour':
        return CqlInteger(_a_ord_ms(b_n) // 3600000 - _a_ord_ms(a_n) // 3600000)
    if unit == 'minute':
        return CqlInteger(_a_ord_ms(b_n) // 60000 - _a_ord_ms(a_n) // 60000)
    if unit == 'second':
        return CqlInteger(_a_ord_ms(b_n) // 1000 - _a_ord_ms(a_n) // 1000)
    if unit == 'millisecond':
        return CqlInteger(_a_ord_ms(b_n) - _a_ord_ms(a_n))
    raise ValueError(f"Unknown unit: {unit}")


def _diff_time(a, b, unit):
    a_f = a.filled_low()
    b_f = b.filled_low()
    if unit == 'hour':
        return CqlInteger(b_f.hour - a_f.hour)
    if unit == 'minute':
        a_total = a_f.hour * 60 + a_f.minute
        b_total = b_f.hour * 60 + b_f.minute
        return CqlInteger(b_total - a_total)
    if unit == 'second':
        a_total = a_f.hour * 3600 + a_f.minute * 60 + a_f.second
        b_total = b_f.hour * 3600 + b_f.minute * 60 + b_f.second
        return CqlInteger(b_total - a_total)
    if unit == 'millisecond':
        return CqlInteger(b_f.to_total_ms() - a_f.to_total_ms())
    raise ValueError(f"Unknown time unit: {unit}")


# ======================== SameAs ========================

def eval_same_as(node):
    a = evaluate(node.a)
    b = evaluate(node.b)
    precision = node.precision
    if isinstance(a, CqlDateTime) and isinstance(b, CqlDateTime):
        prec_idx = prec_index(precision)
        if prec_index(a.precision) < prec_idx or prec_index(b.precision) < prec_idx:
            return CqlNull()
        a_comps = a.component_tuple(precision)
        b_comps = b.component_tuple(precision)
        return CqlBoolean(a_comps == b_comps)
    if isinstance(a, CqlTime) and isinstance(b, CqlTime):
        prec_map = {'hour': 0, 'minute': 1, 'second': 2, 'millisecond': 3}
        idx = prec_map.get(precision, 0)
        a_comps = [a.hour, a.minute, a.second, a.ms]
        b_comps = [b.hour, b.minute, b.second, b.ms]
        for i in range(idx + 1):
            if a_comps[i] is None or b_comps[i] is None:
                return CqlNull()
            if a_comps[i] != b_comps[i]:
                return CqlBoolean(False)
        return CqlBoolean(True)
    raise ValueError(f"Cannot compare {type(a)} and {type(b)}")


# ======================== After / Before ========================

def eval_after_before(node):
    a = evaluate(node.a)
    b = evaluate(node.b)
    precision = node.precision
    direction = node.direction
    if isinstance(a, CqlDateTime) and isinstance(b, CqlDateTime):
        prec_idx = prec_index(precision)
        if prec_index(a.precision) >= prec_idx and prec_index(b.precision) >= prec_idx:
            a_comps = a.component_tuple(precision)
            b_comps = b.component_tuple(precision)
            if direction == 'after':
                return CqlBoolean(a_comps > b_comps)
            else:
                return CqlBoolean(a_comps < b_comps)
        results = set()
        for a_bound in [a.filled_low(), a.filled_high()]:
            for b_bound in [b.filled_low(), b.filled_high()]:
                a_c = a_bound.component_tuple(precision)
                b_c = b_bound.component_tuple(precision)
                if direction == 'after':
                    results.add(a_c > b_c)
                else:
                    results.add(a_c < b_c)
        if len(results) == 1:
            return CqlBoolean(results.pop())
        return CqlNull()
    if isinstance(a, CqlTime) and isinstance(b, CqlTime):
        prec_map = {'hour': 0, 'minute': 1, 'second': 2, 'millisecond': 3}
        idx = prec_map[precision]
        a_comps = [a.hour, a.minute, a.second, a.ms]
        b_comps = [b.hour, b.minute, b.second, b.ms]
        a_t = tuple(c or 0 for c in a_comps[:idx+1])
        b_t = tuple(c or 0 for c in b_comps[:idx+1])
        if direction == 'after':
            return CqlBoolean(a_t > b_t)
        else:
            return CqlBoolean(a_t < b_t)
    raise ValueError(f"Cannot compare {type(a)} and {type(b)}")


# ======================== Comparison ========================

def eval_comparison(node):
    left = evaluate(node.left)
    right = evaluate(node.right)
    op = node.op
    if isinstance(left, CqlInterval):
        return _compare_interval_scalar(left, right, op)
    if isinstance(right, CqlInterval):
        flipped = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '=': '='}
        return _compare_interval_scalar(right, left, flipped[op])
    lv = _extract_comparable(left)
    rv = _extract_comparable(right)
    if lv is None or rv is None:
        return CqlNull()
    return CqlBoolean(_compare_values(lv, rv, op))


def _extract_comparable(val):
    if isinstance(val, CqlNull): return None
    if isinstance(val, CqlBoolean): return val.value
    if isinstance(val, CqlInteger): return val.value
    if isinstance(val, CqlDateTime): return val.component_tuple(val.precision)
    if isinstance(val, CqlTime):
        f = val.filled_low()
        comps = [f.hour]
        if val.minute is not None: comps.append(f.minute)
        if val.second is not None: comps.append(f.second)
        if val.ms is not None: comps.append(f.ms)
        return tuple(comps)
    return None


def _compare_values(lv, rv, op):
    if op == '=': return lv == rv
    elif op == '>': return lv > rv
    elif op == '<': return lv < rv
    elif op == '>=': return lv >= rv
    elif op == '<=': return lv <= rv
    raise ValueError(f"Unknown operator: {op}")


def _compare_interval_scalar(interval, scalar, op):
    if isinstance(scalar, CqlInteger):
        sv = scalar.value
    else:
        sv = _extract_comparable(scalar)
    if sv is None:
        return CqlNull()
    lo, hi = interval.low, interval.high
    if op == '>':
        if lo > sv: return CqlBoolean(True)
        if hi <= sv: return CqlBoolean(False)
        return CqlNull()
    elif op == '<':
        if hi < sv: return CqlBoolean(True)
        if lo >= sv: return CqlBoolean(False)
        return CqlNull()
    elif op == '>=':
        if lo >= sv: return CqlBoolean(True)
        if hi < sv: return CqlBoolean(False)
        return CqlNull()
    elif op == '<=':
        if hi <= sv: return CqlBoolean(True)
        if lo > sv: return CqlBoolean(False)
        return CqlNull()
    elif op == '=':
        if lo == hi == sv: return CqlBoolean(True)
        if sv < lo or sv > hi: return CqlBoolean(False)
        return CqlNull()
    raise ValueError(f"Unknown op: {op}")


# ======================== Formatter ========================

def format_result(value):
    if isinstance(value, CqlNull): return "null"
    if isinstance(value, CqlBoolean): return "true" if value.value else "false"
    if isinstance(value, CqlInteger): return str(value.value)
    if isinstance(value, CqlInterval): return f"Interval[ {value.low}, {value.high} ]"
    if isinstance(value, CqlDateTime): return format_datetime(value)
    if isinstance(value, CqlTime): return format_time(value)
    return str(value)


def format_datetime(dt):
    prec = dt.precision
    if dt.is_date:
        s = f"@{dt.year:04d}"
        if prec == 'year': return s
        s += f"-{dt.month:02d}"
        if prec == 'month': return s
        s += f"-{dt.day:02d}"
        return s
    else:
        s = f"@{dt.year:04d}"
        if prec == 'year': return s + "T"
        s += f"-{dt.month:02d}"
        if prec == 'month': return s + "T"
        s += f"-{dt.day:02d}T"
        if prec == 'day': return _append_tz(s, dt)
        s += f"{dt.hour:02d}"
        if prec == 'hour': return _append_tz(s, dt)
        s += f":{dt.minute:02d}"
        if prec == 'minute': return _append_tz(s, dt)
        s += f":{dt.second:02d}"
        if prec == 'second': return _append_tz(s, dt)
        s += f".{dt.ms:03d}"
        return _append_tz(s, dt)


def _append_tz(s, dt):
    if dt.tz is not None:
        tz = dt.tz
        sign = '+' if tz >= 0 else '-'
        tz_abs = abs(tz)
        tz_h = int(tz_abs)
        tz_m = int((tz_abs - tz_h) * 60)
        s += f"{sign}{tz_h:02d}:{tz_m:02d}"
    return s


def format_time(t):
    s = f"@T{t.hour:02d}"
    if t.precision == 'hour': return s
    s += f":{t.minute:02d}"
    if t.precision == 'minute': return s
    s += f":{t.second:02d}"
    if t.precision == 'second': return s
    s += f".{t.ms:03d}"
    return s


# ======================== XML Processing ========================

TEST_NS = "http://hl7.org/fhirpath/tests"
REPORT_NS = "http://hl7.org/fhirpath/tests/report"


def validate_xml(schema_path, xml_paths, log_path):
    """Run xmllint --schema validation and write log."""
    lines = []
    for xml_path in xml_paths:
        proc = subprocess.run(
            ["xmllint", "--schema", schema_path, "--noout", xml_path],
            capture_output=True, text=True
        )
        lines.append(proc.stderr.strip())
    with open(log_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def parse_test_suites(suites_dir):
    """Parse all XML test suite files and extract test cases."""
    suites = []
    xml_files = sorted(glob.glob(os.path.join(suites_dir, '*.xml')))
    for xml_file in xml_files:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        suite_name = root.get('name', os.path.basename(xml_file))
        source = os.path.basename(xml_file)
        tests = []
        for group in root.findall(f'{{{TEST_NS}}}group'):
            group_name = group.get('name', '')
            for test_el in group.findall(f'{{{TEST_NS}}}test'):
                test_name = test_el.get('name', '')
                expr_el = test_el.find(f'{{{TEST_NS}}}expression')
                expression = expr_el.text or ''
                invalid = expr_el.get('invalid')
                output_els = test_el.findall(f'{{{TEST_NS}}}output')
                expected = (output_els[0].text or '') if output_els else ''
                tests.append({
                    'name': test_name,
                    'group': group_name,
                    'expression': expression,
                    'expected': expected,
                    'invalid': invalid,
                    'has_output': len(output_els) > 0,
                })
        suites.append({'name': suite_name, 'source': source, 'tests': tests})
    return suites, xml_files


def generate_report(suites, eval_results, report_path):
    """Generate conformance report XML."""
    ET.register_namespace('', REPORT_NS)
    root = ET.Element(f'{{{REPORT_NS}}}conformance-report')
    root.set('generated', datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))

    total = passed = failed = errored = skipped = 0
    for suite in suites:
        suite_el = ET.SubElement(root, f'{{{REPORT_NS}}}suite')
        suite_el.set('name', suite['name'])
        suite_el.set('source', suite['source'])
        for test in suite['tests']:
            tr = ET.SubElement(suite_el, f'{{{REPORT_NS}}}test-result')
            tr.set('name', test['name'])
            tr.set('group', test['group'])

            result = eval_results.get(test['name'], {'status': 'error', 'computed': ''})
            tr.set('status', result['status'])

            expr_el = ET.SubElement(tr, f'{{{REPORT_NS}}}expression')
            expr_el.text = test['expression']
            exp_el = ET.SubElement(tr, f'{{{REPORT_NS}}}expected')
            exp_el.text = test['expected']
            comp_el = ET.SubElement(tr, f'{{{REPORT_NS}}}computed')
            comp_el.text = result['computed']

            total += 1
            s = result['status']
            if s == 'pass': passed += 1
            elif s == 'fail': failed += 1
            elif s == 'error': errored += 1
            elif s == 'skip': skipped += 1

    summary = ET.SubElement(root, f'{{{REPORT_NS}}}summary')
    summary.set('total', str(total))
    summary.set('passed', str(passed))
    summary.set('failed', str(failed))
    summary.set('errored', str(errored))
    summary.set('skipped', str(skipped))

    tree = ET.ElementTree(root)
    ET.indent(tree, space='  ')
    tree.write(report_path, encoding='UTF-8', xml_declaration=True)


# ======================== Main ========================

def main():
    suites_dir = '/app/test_suites'

    # Step 1: Validate input XML
    xml_files = sorted(glob.glob(os.path.join(suites_dir, '*.xml')))
    validate_xml('/app/testSchema.xsd', xml_files, '/app/input_validation.log')

    # Step 2: Parse test suites
    suites, _ = parse_test_suites(suites_dir)

    # Step 3: Evaluate expressions
    eval_results = {}
    for suite in suites:
        for test in suite['tests']:
            if test['invalid']:
                eval_results[test['name']] = {'status': 'skip', 'computed': ''}
                continue
            try:
                tokens = tokenize(test['expression'])
                parser = Parser(tokens)
                ast = parser.parse()
                value = evaluate(ast)
                computed = format_result(value)
                if test['has_output']:
                    status = 'pass' if computed == test['expected'] else 'fail'
                else:
                    status = 'pass'
                eval_results[test['name']] = {'status': status, 'computed': computed}
            except Exception as e:
                eval_results[test['name']] = {'status': 'error', 'computed': f'error: {e}'}

    # Step 4: Generate report
    generate_report(suites, eval_results, '/app/report.xml')

    # Step 5: Validate report
    validate_xml('/app/reportSchema.xsd', ['/app/report.xml'], '/app/output_validation.log')


if __name__ == '__main__':
    main()
