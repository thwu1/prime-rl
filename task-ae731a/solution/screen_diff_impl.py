"""Terminal screen diff engine — reference implementation.

Generates minimal ANSI escape sequences to transform one terminal
screen state into another, skipping unchanged cells and tracking
SGR state to emit only delta attribute changes.
"""


def generate_diff(before, after):
    """Generate minimal ANSI escape sequences to transform before into after.

    Assumes SGR is reset to defaults and pending_wrap is cleared
    when the diff is applied. Cursor starts at before['cursor'].
    """
    rows = after['rows']
    cols = after['cols']

    output = bytearray()

    cur_row = before['cursor']['row']
    cur_col = before['cursor']['col']
    cur_fg = None
    cur_bg = None
    cur_bold = False
    cur_underline = False
    cur_reverse = False

    for r in range(rows):
        for c in range(cols):
            bc = before['screen'][r][c]
            ac = after['screen'][r][c]

            if _cells_equal(bc, ac):
                continue

            if cur_row != r or cur_col != c:
                output.extend(f'\x1b[{r + 1};{c + 1}H'.encode())
                cur_row = r
                cur_col = c

            sgr = _build_sgr_delta(
                cur_fg, cur_bg, cur_bold, cur_underline, cur_reverse,
                ac.get('fg'), ac.get('bg'),
                ac.get('bold', False), ac.get('underline', False),
                ac.get('reverse', False),
            )
            if sgr:
                output.extend(sgr)
                cur_fg = ac.get('fg')
                cur_bg = ac.get('bg')
                cur_bold = ac.get('bold', False)
                cur_underline = ac.get('underline', False)
                cur_reverse = ac.get('reverse', False)

            output.extend(ac['char'].encode())
            cur_col += 1
            if cur_col >= cols:
                cur_col = cols - 1

    target = after['cursor']
    if cur_row != target['row'] or cur_col != target['col']:
        output.extend(
            f"\x1b[{target['row'] + 1};{target['col'] + 1}H".encode()
        )

    return bytes(output)


def _cells_equal(a, b):
    return (a['char'] == b['char']
            and _color_eq(a.get('fg'), b.get('fg'))
            and _color_eq(a.get('bg'), b.get('bg'))
            and a.get('bold', False) == b.get('bold', False)
            and a.get('underline', False) == b.get('underline', False)
            and a.get('reverse', False) == b.get('reverse', False))


def _color_eq(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, list) and isinstance(b, list):
        return a == b
    return a == b


def _build_sgr_delta(cur_fg, cur_bg, cur_bold, cur_ul, cur_rev,
                      tgt_fg, tgt_bg, tgt_bold, tgt_ul, tgt_rev):
    parts = []

    if tgt_bold != cur_bold:
        parts.append('1' if tgt_bold else '22')
    if tgt_ul != cur_ul:
        parts.append('4' if tgt_ul else '24')
    if tgt_rev != cur_rev:
        parts.append('7' if tgt_rev else '27')

    if not _color_eq(tgt_fg, cur_fg):
        parts.extend(_encode_color(tgt_fg, foreground=True))
    if not _color_eq(tgt_bg, cur_bg):
        parts.extend(_encode_color(tgt_bg, foreground=False))

    if not parts:
        return b''
    return f"\x1b[{';'.join(parts)}m".encode()


def _encode_color(color, foreground=True):
    if color is None:
        return ['39' if foreground else '49']
    if isinstance(color, list):
        base = '38' if foreground else '48'
        return [f'{base};2;{color[0]};{color[1]};{color[2]}']
    if color > 7:
        base = '38' if foreground else '48'
        return [f'{base};5;{color}']
    offset = 30 if foreground else 40
    return [str(offset + color)]
