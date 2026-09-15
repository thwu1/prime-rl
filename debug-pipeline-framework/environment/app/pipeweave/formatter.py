"""Output formatting utilities with ANSI colour support.

Provides ANSI-aware string operations (strip, visible width, padding)
and a ``TableFormatter`` that renders record lists as aligned text tables.
"""
import re


class FormatterError(Exception):
    pass


_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9]+m')


def strip_ansi(text):
    """Remove ANSI escape sequences from *text*."""
    return _ANSI_ESCAPE.sub('', text)


def visible_width(text):
    """Visible character count (ignoring ANSI escapes)."""
    return len(strip_ansi(text))


def colorize(text, color):
    """Wrap *text* in the ANSI code for *color* and append a reset."""
    colors = {
        'red': '\x1b[31m',
        'green': '\x1b[32m',
        'yellow': '\x1b[33m',
        'blue': '\x1b[34m',
        'magenta': '\x1b[35m',
        'cyan': '\x1b[36m',
        'bold': '\x1b[1m',
        'bold_red': '\x1b[1;31m',
        'bold_green': '\x1b[1;32m',
        'bold_yellow': '\x1b[1;33m',
        'dim': '\x1b[2m',
    }
    code = colors.get(color, '')
    if not code:
        return text
    return f"{code}{text}\x1b[0m"


def pad_to_width(text, width, align='left'):
    """Pad *text* to *width* visible characters, respecting ANSI codes."""
    current = visible_width(text)
    padding = max(0, width - current)
    if align == 'right':
        return ' ' * padding + text
    elif align == 'center':
        lp = padding // 2
        return ' ' * lp + text + ' ' * (padding - lp)
    return text + ' ' * padding


class TableFormatter:
    """Renders a list of record dicts as an aligned text table.

    Parameters
    ----------
    columns : list[dict]
        Each dict may contain ``field``, ``header``, ``width``, ``align``,
        ``format``.
    color_rules : list[tuple]
        ``(field, condition_fn, color)`` triples; the first matching rule wins.
    separator : str
        Column separator (default ``' | '``).
    """

    def __init__(self, columns=None, color_rules=None, separator=' | '):
        self.columns = columns or []
        self.color_rules = color_rules or []
        self.separator = separator

    def format_value(self, value, fmt=None):
        if value is None:
            return ''
        if fmt and isinstance(value, float):
            return format(value, fmt)
        if fmt and isinstance(value, int):
            return format(value, fmt)
        return str(value)

    def apply_color_rules(self, record, field, text):
        for rule_field, condition, color in self.color_rules:
            if rule_field == field and condition(record):
                return colorize(text, color)
        return text

    def format_header(self):
        cells = []
        for col in self.columns:
            header = col.get('header', col['field'])
            width = col.get('width', len(header))
            cells.append(pad_to_width(header, width, col.get('align', 'left')))
        header_line = self.separator.join(cells)
        return header_line + '\n' + '-' * visible_width(header_line)

    def format_record(self, record):
        cells = []
        for col in self.columns:
            raw = record.get(col['field'])
            text = self.format_value(raw, col.get('format'))
            text = self.apply_color_rules(record, col['field'], text)
            width = col.get('width', len(col.get('header', col['field'])))
            cells.append(pad_to_width(text, width, col.get('align', 'left')))
        return self.separator.join(cells)

    def format_table(self, records):
        if not records:
            return ''

        # Auto-detect columns when not specified
        if not self.columns:
            seen = set()
            fields = []
            for rec in records:
                for f in rec:
                    if f not in seen:
                        fields.append(f)
                        seen.add(f)
            self.columns = [{'field': f, 'header': f} for f in fields]

        # Auto-calculate widths
        for col in self.columns:
            if 'width' not in col:
                hw = len(col.get('header', col['field']))
                mw = max(
                    (len(self.format_value(r.get(col['field']), col.get('format')))
                     for r in records),
                    default=0,
                )
                col['width'] = max(hw, mw)

        lines = [self.format_header()]
        for rec in records:
            lines.append(self.format_record(rec))
        return '\n'.join(lines)

    def format_summary(self, records, agg_fields=None):
        if not records:
            return 'No records.'
        parts = [f"Total: {len(records)} records"]
        if agg_fields:
            for field, agg in agg_fields.items():
                vals = [r.get(field) for r in records
                        if r.get(field) is not None]
                if not vals:
                    continue
                if agg == 'sum':
                    parts.append(f"{field} sum: {sum(vals)}")
                elif agg == 'avg':
                    parts.append(f"{field} avg: {sum(vals)/len(vals):.2f}")
                elif agg == 'min':
                    parts.append(f"{field} min: {min(vals)}")
                elif agg == 'max':
                    parts.append(f"{field} max: {max(vals)}")
        return ' | '.join(parts)
