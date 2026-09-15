#!/usr/bin/env python3
"""FHIRPath Quantity Expression Evaluator."""

import sys
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# ── Unit classification ──

CALENDAR_DURATION_SECONDS = {
    'years': 31536000, 'year': 31536000,
    'months': 2592000, 'month': 2592000,
    'weeks': 604800, 'week': 604800,
    'days': 86400, 'day': 86400,
    'hours': 3600, 'hour': 3600,
    'minutes': 60, 'minute': 60,
    'seconds': 1, 'second': 1,
    'milliseconds': Decimal('0.001'), 'millisecond': Decimal('0.001'),
}

YEAR_MONTH_FACTOR = {
    'years': 12, 'year': 12,
    'months': 1, 'month': 1,
}

ABOVE_WEEKS = {'years', 'year', 'months', 'month'}

# UCUM time unit mapping to calendar equivalents (for cross-system comparison)
UCUM_TIME_TO_CALENDAR = {
    's': 'second', 'min': 'minute', 'h': 'hour',
}

CALENDAR_TO_UCUM_TIME = {
    'second': 's', 'seconds': 's',
    'minute': 'min', 'minutes': 'min',
    'hour': 'h', 'hours': 'h',
    'day': 'd', 'days': 'd',
    'week': 'wk', 'weeks': 'wk',
    'millisecond': 'ms', 'milliseconds': 'ms',
}

# UCUM conversion to base units: unit -> (factor, base_unit)
UCUM_CONVERSIONS = {
    'kg': (Decimal('1'), 'kg'),
    'g': (Decimal('0.001'), 'kg'),
    'mg': (Decimal('0.000001'), 'kg'),
    'km': (Decimal('1000'), 'm'),
    'm': (Decimal('1'), 'm'),
    'cm': (Decimal('0.01'), 'm'),
    's': (Decimal('1'), 's_ucum'),
    'min': (Decimal('60'), 's_ucum'),
    'h': (Decimal('3600'), 's_ucum'),
    '1': (Decimal('1'), '1'),
}


def is_calendar(unit):
    return unit in CALENDAR_DURATION_SECONDS


def is_ucum(unit):
    return unit.startswith("'") and unit.endswith("'")


def strip_ucum(unit):
    if unit.startswith("'") and unit.endswith("'"):
        return unit[1:-1]
    return unit


def format_number(val):
    """Format a Decimal nicely: strip trailing zeros, no trailing dot."""
    if val == val.to_integral_value():
        return str(int(val))
    # Normalize removes trailing zeros but may produce scientific notation
    normalized = val.normalize()
    s = str(normalized)
    if 'E' in s or 'e' in s:
        return format(val, 'f').rstrip('0').rstrip('.')
    return s


# ── Value types ──

class Quantity:
    def __init__(self, value, unit):
        self.value = Decimal(str(value))
        self.unit = unit  # calendar unit string or "'ucum'" with quotes

    def __repr__(self):
        return f"Qty({self.value} {self.unit})"


class BoolResult:
    def __init__(self, val):
        self.val = val


class Empty:
    """Represents {} (empty/incomparable)."""
    pass


def format_result(r):
    if isinstance(r, Empty):
        return "{}"
    if isinstance(r, BoolResult):
        return "true" if r.val else "false"
    if isinstance(r, Quantity):
        return f"{format_number(r.value)} {r.unit}"
    if isinstance(r, Decimal):
        return format_number(r)
    return str(r)


# ── Tokenizer ──

TOKEN_SPEC = [
    ('NUMBER', r'\d+\.?\d*'),
    ('UCUM_UNIT', r"'[^']*'"),
    ('OP', r'!=|<=|>=|[+\-*/=<>]'),
    ('LPAREN', r'\('),
    ('RPAREN', r'\)'),
    ('WORD', r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ('SKIP', r'\s+'),
]

TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pat})' for name, pat in TOKEN_SPEC))


def tokenize(expr):
    tokens = []
    for m in TOKEN_RE.finditer(expr):
        kind = m.lastgroup
        val = m.group()
        if kind == 'SKIP':
            continue
        tokens.append((kind, val))
    return tokens


# ── Parser (recursive descent) ──

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self):
        result = self.parse_comparison()
        return result

    def parse_comparison(self):
        left = self.parse_additive()
        while self.peek() and self.peek()[0] == 'OP' and self.peek()[1] in ('=', '!=', '<', '>', '<=', '>='):
            op = self.consume()[1]
            right = self.parse_additive()
            left = ('binop', op, left, right)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.peek() and self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.consume()[1]
            right = self.parse_multiplicative()
            left = ('binop', op, left, right)
        return left

    def parse_multiplicative(self):
        left = self.parse_primary()
        while self.peek() and self.peek()[0] == 'OP' and self.peek()[1] in ('*', '/'):
            op = self.consume()[1]
            right = self.parse_primary()
            left = ('binop', op, left, right)
        return left

    def parse_primary(self):
        tok = self.peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")

        if tok[0] == 'LPAREN':
            self.consume()
            node = self.parse_comparison()
            if not self.peek() or self.peek()[0] != 'RPAREN':
                raise ValueError("Expected )")
            self.consume()
            # Check if followed by a unit (shouldn't normally be, but handle)
            return node

        if tok[0] == 'NUMBER':
            self.consume()
            num_val = Decimal(tok[1])
            # Check if followed by a unit
            nxt = self.peek()
            if nxt and nxt[0] == 'UCUM_UNIT':
                self.consume()
                return ('quantity', num_val, nxt[1])
            if nxt and nxt[0] == 'WORD' and nxt[1] in CALENDAR_DURATION_SECONDS:
                self.consume()
                return ('quantity', num_val, nxt[1])
            return ('number', num_val)

        if tok[0] == 'OP' and tok[1] == '-':
            self.consume()
            inner = self.parse_primary()
            return ('neg', inner)

        raise ValueError(f"Unexpected token: {tok}")


# ── Evaluator ──

def evaluate(node):
    if node[0] == 'number':
        return Decimal(str(node[1]))

    if node[0] == 'quantity':
        return Quantity(node[1], node[2])

    if node[0] == 'neg':
        val = evaluate(node[1])
        if isinstance(val, Decimal):
            return -val
        if isinstance(val, Quantity):
            return Quantity(-val.value, val.unit)
        return Empty()

    if node[0] == 'binop':
        op = node[1]
        left = evaluate(node[2])
        right = evaluate(node[3])

        if isinstance(left, Empty) or isinstance(right, Empty):
            return Empty()

        if op in ('=', '!=', '<', '>', '<=', '>='):
            return eval_comparison(op, left, right)
        if op in ('+', '-'):
            return eval_add_sub(op, left, right)
        if op == '*':
            return eval_mul(left, right)
        if op == '/':
            return eval_div(left, right)

    raise ValueError(f"Unknown node: {node}")


def both_plain(left, right):
    return isinstance(left, Decimal) and isinstance(right, Decimal)


def convert_ucum_to_base(unit_code):
    """Convert a UCUM unit code to (factor, base_dimension)."""
    if unit_code in UCUM_CONVERSIONS:
        return UCUM_CONVERSIONS[unit_code]
    return None


def calendar_to_seconds(unit):
    """Get second-equivalent for a calendar unit."""
    val = CALENDAR_DURATION_SECONDS.get(unit)
    if val is not None:
        return Decimal(str(val))
    return None


def get_ucum_code(unit):
    """Strip quotes from UCUM unit."""
    return strip_ucum(unit)


def can_compare_cross_system(cal_unit, ucum_code):
    """Check if a calendar unit and UCUM time unit can be compared."""
    # Above-week calendar units (year, month) cannot compare with UCUM time
    if cal_unit in ABOVE_WEEKS:
        return False
    # Below-week calendar units can compare with UCUM time if UCUM is a time unit
    if ucum_code in UCUM_TIME_TO_CALENDAR:
        return True
    # Also handle 'd', 'wk', 'ms'
    if ucum_code in ('d', 'wk', 'ms'):
        return True
    return False


def calendar_unit_to_seconds_decimal(unit):
    v = CALENDAR_DURATION_SECONDS.get(unit)
    if v is not None:
        return Decimal(str(v))
    return None


def ucum_time_to_seconds(code):
    mapping = {'s': Decimal('1'), 'min': Decimal('60'), 'h': Decimal('3600'),
               'd': Decimal('86400'), 'wk': Decimal('604800'), 'ms': Decimal('0.001')}
    return mapping.get(code)


# ── Comparison ──

def eval_comparison(op, left, right):
    if both_plain(left, right):
        return BoolResult(compare_op(op, left, right))

    if isinstance(left, Quantity) and isinstance(right, Quantity):
        cmp = compare_quantities(left, right)
        if cmp is None:
            return Empty()
        return BoolResult(compare_op_val(op, cmp))

    if isinstance(left, Decimal) and isinstance(right, Quantity):
        # Treat number as quantity with unit '1'
        left = Quantity(left, "'1'")
        cmp = compare_quantities(left, right)
        if cmp is None:
            return Empty()
        return BoolResult(compare_op_val(op, cmp))

    if isinstance(left, Quantity) and isinstance(right, Decimal):
        right = Quantity(right, "'1'")
        cmp = compare_quantities(left, right)
        if cmp is None:
            return Empty()
        return BoolResult(compare_op_val(op, cmp))

    return Empty()


def compare_op(op, a, b):
    if op == '=': return a == b
    if op == '!=': return a != b
    if op == '<': return a < b
    if op == '>': return a > b
    if op == '<=': return a <= b
    if op == '>=': return a >= b


def compare_op_val(op, cmp):
    """cmp is -1, 0, or 1."""
    if op == '=': return cmp == 0
    if op == '!=': return cmp != 0
    if op == '<': return cmp < 0
    if op == '>': return cmp > 0
    if op == '<=': return cmp <= 0
    if op == '>=': return cmp >= 0


def compare_quantities(a, b):
    """Compare two quantities. Returns -1, 0, 1, or None (incomparable)."""
    a_cal = is_calendar(a.unit)
    b_cal = is_calendar(b.unit)
    a_ucum = is_ucum(a.unit)
    b_ucum = is_ucum(b.unit)

    # Both calendar
    if a_cal and b_cal:
        return compare_calendar(a, b)

    # Both UCUM
    if a_ucum and b_ucum:
        return compare_ucum(a, b)

    # Mixed: calendar vs UCUM
    if a_cal and b_ucum:
        ucum_code = get_ucum_code(b.unit)
        if not can_compare_cross_system(a.unit, ucum_code):
            return None
        # Convert both to seconds
        a_secs = a.value * calendar_unit_to_seconds_decimal(a.unit)
        b_secs_factor = ucum_time_to_seconds(ucum_code)
        if b_secs_factor is None:
            return None
        b_secs = b.value * b_secs_factor
        return decimal_cmp(a_secs, b_secs)

    if a_ucum and b_cal:
        ucum_code = get_ucum_code(a.unit)
        if not can_compare_cross_system(b.unit, ucum_code):
            return None
        a_secs_factor = ucum_time_to_seconds(ucum_code)
        if a_secs_factor is None:
            return None
        a_secs = a.value * a_secs_factor
        b_secs = b.value * calendar_unit_to_seconds_decimal(b.unit)
        return decimal_cmp(a_secs, b_secs)

    return None


def compare_calendar(a, b):
    """Compare two calendar duration quantities."""
    # Year/month special case
    a_ym = YEAR_MONTH_FACTOR.get(a.unit)
    b_ym = YEAR_MONTH_FACTOR.get(b.unit)
    if a_ym is not None and b_ym is not None:
        a_months = a.value * a_ym
        b_months = b.value * b_ym
        return decimal_cmp(a_months, b_months)

    # Convert via seconds
    a_secs = a.value * calendar_unit_to_seconds_decimal(a.unit)
    b_secs = b.value * calendar_unit_to_seconds_decimal(b.unit)
    return decimal_cmp(a_secs, b_secs)


def compare_ucum(a, b):
    """Compare two UCUM quantities."""
    a_code = get_ucum_code(a.unit)
    b_code = get_ucum_code(b.unit)

    a_conv = convert_ucum_to_base(a_code)
    b_conv = convert_ucum_to_base(b_code)

    if a_conv is None or b_conv is None:
        return None
    if a_conv[1] != b_conv[1]:
        return None  # Different dimensions

    a_base = a.value * a_conv[0]
    b_base = b.value * b_conv[0]
    return decimal_cmp(a_base, b_base)


def decimal_cmp(a, b):
    if a < b: return -1
    if a > b: return 1
    return 0


# ── Addition / Subtraction ──

def eval_add_sub(op, left, right):
    if both_plain(left, right):
        if op == '+':
            return left + right
        return left - right

    # Promote plain number to quantity '1' if other side is quantity
    if isinstance(left, Decimal) and isinstance(right, Quantity):
        left = Quantity(left, "'1'")
    if isinstance(left, Quantity) and isinstance(right, Decimal):
        right = Quantity(right, "'1'")

    if isinstance(left, Quantity) and isinstance(right, Quantity):
        return add_sub_quantities(op, left, right)

    return Empty()


def add_sub_quantities(op, a, b):
    a_cal = is_calendar(a.unit)
    b_cal = is_calendar(b.unit)
    a_ucum = is_ucum(a.unit)
    b_ucum = is_ucum(b.unit)

    if a_cal and b_cal:
        return add_sub_calendar(op, a, b)

    if a_ucum and b_ucum:
        return add_sub_ucum(op, a, b)

    # Mixed: calendar vs UCUM — check compatibility
    if a_cal and b_ucum:
        ucum_code = get_ucum_code(b.unit)
        if not can_compare_cross_system(a.unit, ucum_code):
            return Empty()
        # Convert UCUM to calendar seconds, do arithmetic, result in left unit
        a_secs = calendar_unit_to_seconds_decimal(a.unit)
        b_secs_factor = ucum_time_to_seconds(ucum_code)
        if b_secs_factor is None:
            return Empty()
        # Convert b to a's unit
        b_in_a = b.value * b_secs_factor / a_secs
        if op == '+':
            return Quantity(a.value + b_in_a, a.unit)
        return Quantity(a.value - b_in_a, a.unit)

    if a_ucum and b_cal:
        ucum_code = get_ucum_code(a.unit)
        if not can_compare_cross_system(b.unit, ucum_code):
            return Empty()
        a_secs_factor = ucum_time_to_seconds(ucum_code)
        b_secs = calendar_unit_to_seconds_decimal(b.unit)
        if a_secs_factor is None:
            return Empty()
        # Convert b to a's unit
        b_in_a = b.value * b_secs / a_secs_factor
        if op == '+':
            return Quantity(a.value + b_in_a, a.unit)
        return Quantity(a.value - b_in_a, a.unit)

    return Empty()


def add_sub_calendar(op, a, b):
    """Add/subtract two calendar duration quantities."""
    a_ym = YEAR_MONTH_FACTOR.get(a.unit)
    b_ym = YEAR_MONTH_FACTOR.get(b.unit)

    if a_ym is not None and b_ym is not None:
        # Year/month: convert to finer (months)
        a_secs_val = CALENDAR_DURATION_SECONDS[a.unit]
        b_secs_val = CALENDAR_DURATION_SECONDS[b.unit]
        if isinstance(a_secs_val, float):
            a_secs_val = Decimal(str(a_secs_val))
        else:
            a_secs_val = Decimal(str(a_secs_val))
        if isinstance(b_secs_val, float):
            b_secs_val = Decimal(str(b_secs_val))
        else:
            b_secs_val = Decimal(str(b_secs_val))

        # Use year=12months conversion, result in finer unit
        if a_secs_val > b_secs_val:
            # a is coarser (year), b is finer (month)
            a_converted = a.value * Decimal(str(a_ym)) / Decimal(str(b_ym))
            if op == '+':
                result_val = a_converted + b.value
            else:
                result_val = a_converted - b.value
            return Quantity(result_val, b.unit)
        elif b_secs_val > a_secs_val:
            b_converted = b.value * Decimal(str(b_ym)) / Decimal(str(a_ym))
            if op == '+':
                result_val = a.value + b_converted
            else:
                result_val = a.value - b_converted
            return Quantity(result_val, a.unit)
        else:
            # Same granularity
            if op == '+':
                return Quantity(a.value + b.value, a.unit)
            return Quantity(a.value - b.value, a.unit)

    # General calendar: convert via seconds, result in finer unit
    a_secs = Decimal(str(CALENDAR_DURATION_SECONDS[a.unit]))
    b_secs = Decimal(str(CALENDAR_DURATION_SECONDS[b.unit]))

    if a_secs > b_secs:
        # a is coarser, convert a to b's unit
        a_in_b = a.value * a_secs / b_secs
        if op == '+':
            return Quantity(a_in_b + b.value, b.unit)
        return Quantity(a_in_b - b.value, b.unit)
    elif b_secs > a_secs:
        b_in_a = b.value * b_secs / a_secs
        if op == '+':
            return Quantity(a.value + b_in_a, a.unit)
        return Quantity(a.value - b_in_a, a.unit)
    else:
        if op == '+':
            return Quantity(a.value + b.value, a.unit)
        return Quantity(a.value - b.value, a.unit)


def add_sub_ucum(op, a, b):
    """Add/subtract two UCUM quantities."""
    a_code = get_ucum_code(a.unit)
    b_code = get_ucum_code(b.unit)

    if a_code == b_code:
        if op == '+':
            return Quantity(a.value + b.value, a.unit)
        return Quantity(a.value - b.value, a.unit)

    a_conv = convert_ucum_to_base(a_code)
    b_conv = convert_ucum_to_base(b_code)

    if a_conv is None or b_conv is None:
        return Empty()
    if a_conv[1] != b_conv[1]:
        return Empty()  # Incompatible dimensions

    # Convert b to a's unit
    b_in_a = b.value * b_conv[0] / a_conv[0]
    if op == '+':
        return Quantity(a.value + b_in_a, a.unit)
    return Quantity(a.value - b_in_a, a.unit)


# ── Multiplication ──

def eval_mul(left, right):
    if both_plain(left, right):
        return left * right

    # Number * Quantity or Quantity * Number
    if isinstance(left, Decimal) and isinstance(right, Quantity):
        return Quantity(left * right.value, right.unit)
    if isinstance(left, Quantity) and isinstance(right, Decimal):
        return Quantity(left.value * right, left.unit)

    if isinstance(left, Quantity) and isinstance(right, Quantity):
        a_cal = is_calendar(left.unit)
        b_cal = is_calendar(right.unit)
        a_ucum = is_ucum(left.unit)
        b_ucum = is_ucum(right.unit)

        # Calendar * Calendar = empty
        if a_cal and b_cal:
            return Empty()

        # Calendar * UCUM or UCUM * Calendar
        if (a_cal and b_ucum) or (a_ucum and b_cal):
            # Check if one side is unit '1' (dimensionless number)
            if a_ucum:
                code = get_ucum_code(left.unit)
                if code == '1':
                    return Quantity(left.value * right.value, right.unit)
            if b_ucum:
                code = get_ucum_code(right.unit)
                if code == '1':
                    return Quantity(left.value * right.value, left.unit)
            return Empty()

        # UCUM * UCUM: produce compound unit
        if a_ucum and b_ucum:
            a_code = get_ucum_code(left.unit)
            b_code = get_ucum_code(right.unit)
            if a_code == '1':
                return Quantity(left.value * right.value, right.unit)
            if b_code == '1':
                return Quantity(left.value * right.value, left.unit)
            compound = f"'{a_code}.{b_code}'"
            return Quantity(left.value * right.value, compound)

    return Empty()


# ── Division ──

def eval_div(left, right):
    # Check for division by zero
    if isinstance(right, Decimal) and right == 0:
        return Empty()
    if isinstance(right, Quantity) and right.value == 0:
        return Empty()

    if both_plain(left, right):
        return left / right

    if isinstance(left, Quantity) and isinstance(right, Decimal):
        return Quantity(left.value / right, left.unit)

    if isinstance(left, Decimal) and isinstance(right, Quantity):
        # number / quantity = quantity with reciprocal unit
        code = get_ucum_code(right.unit) if is_ucum(right.unit) else right.unit
        result_unit = f"'1/{code}'"
        return Quantity(left / right.value, result_unit)

    if isinstance(left, Quantity) and isinstance(right, Quantity):
        a_cal = is_calendar(left.unit)
        b_cal = is_calendar(right.unit)
        a_ucum = is_ucum(left.unit)
        b_ucum = is_ucum(right.unit)

        if a_cal and b_cal:
            return Empty()

        if (a_cal and b_ucum) or (a_ucum and b_cal):
            if b_ucum:
                code = get_ucum_code(right.unit)
                if code == '1':
                    return Quantity(left.value / right.value, left.unit)
            if b_cal:
                return Empty()
            return Empty()

        if a_ucum and b_ucum:
            a_code = get_ucum_code(left.unit)
            b_code = get_ucum_code(right.unit)
            if b_code == '1':
                return Quantity(left.value / right.value, left.unit)
            if a_code == b_code:
                return Quantity(left.value / right.value, "'1'")
            compound = f"'{a_code}/{b_code}'"
            return Quantity(left.value / right.value, compound)

    return Empty()


# ── Main ──

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fhirpath_qty.py '<expression>'", file=sys.stderr)
        sys.exit(1)

    expr = sys.argv[1]
    tokens = tokenize(expr)
    parser = Parser(tokens)
    ast = parser.parse()
    result = evaluate(ast)
    print(format_result(result))


if __name__ == '__main__':
    main()
