"""CSS value resolution: var() substitution and calc()/min()/max()/clamp() evaluation."""

import re


# ============================================================================
# var() parsing and substitution
# ============================================================================

def _parse_var_call(value, start):
    """Parse a var(...) call starting at position ``start``.

    Returns (property_name, fallback_or_None, end_position).
    """
    pos = start + 4  # skip "var("
    while pos < len(value) and value[pos] in ' \t\n\r':
        pos += 1
    name_start = pos
    while pos < len(value) and value[pos] not in ' \t\n\r,)':
        pos += 1
    name = value[name_start:pos]
    while pos < len(value) and value[pos] in ' \t\n\r':
        pos += 1
    fallback = None
    if pos < len(value) and value[pos] == ',':
        pos += 1
        depth = 1
        fb_start = pos
        while pos < len(value) and depth > 0:
            if value[pos] == '(':
                depth += 1
            elif value[pos] == ')':
                depth -= 1
                if depth == 0:
                    break
            pos += 1
        fallback = value[fb_start:pos].strip()
    if pos < len(value) and value[pos] == ')':
        pos += 1
    return name, fallback, pos


def resolve_var_references(value, custom_props, visited=None):
    """Recursively substitute all var() references in *value*.

    Parameters
    ----------
    value : str | None
        The CSS value string (may contain var() calls).
    custom_props : dict
        Mapping ``--name`` → resolved value (str) or ``None`` for
        guaranteed-invalid.
    visited : set | None
        Property names currently being resolved (for cycle detection).

    Returns
    -------
    str | None
        Resolved string, or ``None`` if guaranteed-invalid.
    """
    if value is None:
        return None
    if visited is None:
        visited = set()

    result = []
    i = 0
    while i < len(value):
        if value[i:i + 4] == 'var(':
            name, fallback, end = _parse_var_call(value, i)
            resolved_part = None

            if name in visited:
                # Cycle detected
                if fallback is not None:
                    resolved_part = resolve_var_references(
                        fallback, custom_props, visited.copy())
            elif name in custom_props:
                prop_val = custom_props[name]
                if prop_val is None:
                    # Guaranteed-invalid upstream
                    if fallback is not None:
                        resolved_part = resolve_var_references(
                            fallback, custom_props, visited.copy())
                else:
                    new_visited = visited | {name}
                    resolved_part = resolve_var_references(
                        prop_val, custom_props, new_visited)
                    if resolved_part is None and fallback is not None:
                        resolved_part = resolve_var_references(
                            fallback, custom_props, visited.copy())
            else:
                # Not defined
                if fallback is not None:
                    resolved_part = resolve_var_references(
                        fallback, custom_props, visited.copy())

            if resolved_part is None:
                return None  # guaranteed-invalid, no fallback
            result.append(resolved_part)
            i = end
        else:
            result.append(value[i])
            i += 1

    return ''.join(result)


# ============================================================================
# calc() / min() / max() / clamp() evaluation
# ============================================================================

_NUM_RE = re.compile(r'^(-?\d+(?:\.\d+)?)(.*)')


def _parse_num_unit(s):
    """Parse ``'10px'`` into ``(10.0, 'px')``; returns ``(None, None)`` on failure."""
    m = _NUM_RE.match(s.strip())
    if m:
        return float(m.group(1)), m.group(2).strip()
    return None, None


def _format_num(val, unit):
    if val == int(val):
        return f"{int(val)}{unit}"
    rounded = round(val, 4)
    if rounded == int(rounded):
        return f"{int(rounded)}{unit}"
    s = f"{rounded:.4f}".rstrip('0').rstrip('.')
    return f"{s}{unit}"


def _split_args(inner):
    """Split function arguments at top-level commas."""
    args = []
    depth = 0
    current = []
    for ch in inner:
        if ch == ',' and depth == 0:
            args.append(''.join(current))
            current = []
        else:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            current.append(ch)
    if current:
        args.append(''.join(current))
    return args


class _CalcParser:
    """Recursive descent parser for CSS arithmetic expressions."""

    def __init__(self, expr):
        self.expr = expr.strip()
        self.pos = 0

    def parse(self):
        return self._parse_sum()

    # -- grammar -------------------------------------------------------

    def _parse_sum(self):
        left = self._parse_product()
        if left is None:
            return None
        while True:
            self._ws()
            if self.pos >= len(self.expr):
                break
            op = self.expr[self.pos]
            if op in '+-':
                self.pos += 1
                self._ws()
                right = self._parse_product()
                if right is None:
                    return left
                left = self._apply(left, op, right)
                if left is None:
                    return None
            else:
                break
        return left

    def _parse_product(self):
        left = self._parse_primary()
        if left is None:
            return None
        while True:
            self._ws()
            if self.pos >= len(self.expr):
                break
            op = self.expr[self.pos]
            if op in '*/':
                self.pos += 1
                self._ws()
                right = self._parse_primary()
                if right is None:
                    return left
                left = self._apply(left, op, right)
                if left is None:
                    return None
            else:
                break
        return left

    def _parse_primary(self):
        self._ws()
        if self.pos >= len(self.expr):
            return None
        # Nested function
        for prefix in ('calc(', 'min(', 'max(', 'clamp('):
            if self.expr[self.pos:].startswith(prefix):
                return self._parse_func(prefix)
        # Parenthesised sub-expression
        if self.expr[self.pos] == '(':
            self.pos += 1
            result = self._parse_sum()
            self._ws()
            if self.pos < len(self.expr) and self.expr[self.pos] == ')':
                self.pos += 1
            return result
        return self._parse_number()

    def _parse_number(self):
        self._ws()
        start = self.pos
        if self.pos < len(self.expr) and self.expr[self.pos] in '+-':
            self.pos += 1
        has_digits = False
        while self.pos < len(self.expr) and (
                self.expr[self.pos].isdigit() or self.expr[self.pos] == '.'):
            has_digits = True
            self.pos += 1
        if not has_digits:
            self.pos = start
            return None
        num = float(self.expr[start:self.pos])
        u_start = self.pos
        while self.pos < len(self.expr) and (
                self.expr[self.pos].isalpha() or self.expr[self.pos] == '%'):
            self.pos += 1
        unit = self.expr[u_start:self.pos]
        return (num, unit)

    def _parse_func(self, prefix):
        fname = prefix[:-1]
        self.pos += len(prefix)
        if fname == 'calc':
            result = self._parse_sum()
            self._ws()
            if self.pos < len(self.expr) and self.expr[self.pos] == ')':
                self.pos += 1
            return result
        # min / max / clamp — comma-separated args
        args = []
        arg = self._parse_sum()
        if arg is not None:
            args.append(arg)
        while self.pos < len(self.expr):
            self._ws()
            if self.pos >= len(self.expr) or self.expr[self.pos] != ',':
                break
            self.pos += 1
            self._ws()
            arg = self._parse_sum()
            if arg is not None:
                args.append(arg)
        self._ws()
        if self.pos < len(self.expr) and self.expr[self.pos] == ')':
            self.pos += 1
        if not args:
            return None
        units = set(u for _, u in args)
        if len(units) > 1:
            return None
        if fname == 'min':
            return min(args, key=lambda x: x[0])
        if fname == 'max':
            return max(args, key=lambda x: x[0])
        if fname == 'clamp' and len(args) == 3:
            mn, pref, mx = args
            clamped = max(mn[0], min(pref[0], mx[0]))
            return (clamped, mn[1])
        return None

    # -- helpers --------------------------------------------------------

    def _ws(self):
        while self.pos < len(self.expr) and self.expr[self.pos] in ' \t\n\r':
            self.pos += 1

    @staticmethod
    def _apply(left, op, right):
        lv, lu = left
        rv, ru = right
        if op == '+':
            if lu == ru:
                return (lv + rv, lu)
            if lu == '':
                return (lv + rv, ru)
            if ru == '':
                return (lv + rv, lu)
            return None
        if op == '-':
            if lu == ru:
                return (lv - rv, lu)
            if lu == '':
                return (lv - rv, ru)
            if ru == '':
                return (lv - rv, lu)
            return None
        if op == '*':
            if lu == '' or ru == '':
                return (lv * rv, lu or ru)
            return None
        if op == '/':
            if rv == 0:
                return None
            if ru == '':
                return (lv / rv, lu)
            if lu == ru:
                return (lv / rv, '')
            return None
        return None


def _eval_minmaxclamp(fname, inner):
    """Evaluate a min/max/clamp call from its inner (comma-separated) text."""
    args_str = _split_args(inner)
    values = []
    for a in args_str:
        a = a.strip()
        # Recursively evaluate nested math functions in each argument
        a = resolve_math_functions(a)
        num, unit = _parse_num_unit(a)
        if num is None:
            # Might be a bare arithmetic expression (no wrapper)
            parser = _CalcParser(a)
            ev = parser.parse()
            if ev is None:
                return None
            num, unit = ev
        values.append((num, unit))
    if not values:
        return None
    units = set(u for _, u in values)
    if len(units) > 1:
        return None
    if fname == 'min':
        return min(values, key=lambda x: x[0])
    if fname == 'max':
        return max(values, key=lambda x: x[0])
    if fname == 'clamp' and len(values) == 3:
        mn, pref, mx = values
        clamped = max(mn[0], min(pref[0], mx[0]))
        return (clamped, mn[1])
    return None


def resolve_math_functions(value):
    """Find and evaluate calc/min/max/clamp in a CSS value string."""
    if value is None:
        return value

    result = []
    i = 0
    while i < len(value):
        matched = False
        for prefix in ('clamp(', 'calc(', 'min(', 'max('):
            if value[i:].startswith(prefix):
                depth = 0
                j = i + len(prefix) - 1
                while j < len(value):
                    if value[j] == '(':
                        depth += 1
                    elif value[j] == ')':
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                func_str = value[i:j]
                fname = prefix[:-1]
                inner = func_str[len(prefix):-1]
                if fname == 'calc':
                    parser = _CalcParser(inner)
                    ev = parser.parse()
                    if ev is not None:
                        result.append(_format_num(ev[0], ev[1]))
                    else:
                        result.append(func_str)
                else:
                    ev = _eval_minmaxclamp(fname, inner)
                    if ev is not None:
                        result.append(_format_num(ev[0], ev[1]))
                    else:
                        result.append(func_str)
                i = j
                matched = True
                break
        if not matched:
            result.append(value[i])
            i += 1
    return ''.join(result)
