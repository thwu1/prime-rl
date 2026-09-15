def round_val(x, decimals=2):
    return round(float(x), decimals)


def pad_string(s, width, fill_char=' '):
    return str(s).ljust(width, fill_char)


def format_table(rows, headers):
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    lines = []
    header_line = ' | '.join(
        pad_string(h, col_widths[i]) for i, h in enumerate(headers)
    )
    lines.append(header_line)
    lines.append('-' * len(header_line))
    for row in rows:
        line = ' | '.join(
            pad_string(str(cell), col_widths[i]) for i, cell in enumerate(row)
        )
        lines.append(line)
    return '\n'.join(lines)
