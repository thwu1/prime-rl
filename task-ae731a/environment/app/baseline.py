"""Naive full-screen rewrite renderer for efficiency comparison.

This module provides a maximally wasteful renderer that rewrites every cell
on the screen with full SGR sequences. Use it as a baseline to measure
how much more efficient a diff-based approach can be.
"""


def naive_rewrite(after_snap):
    """Generate ANSI bytes that rewrite every cell of the target state.

    Emits CUP + full SGR + character for every single cell regardless of
    what was previously on screen. Returns bytes.
    """
    output = bytearray()
    output.extend(b'\x1b[0m')

    rows = after_snap['rows']
    cols = after_snap['cols']

    for r in range(rows):
        output.extend(f'\x1b[{r + 1};1H'.encode())

        for c in range(cols):
            cell = after_snap['screen'][r][c]

            sgr = '\x1b[0'
            if cell['bold']:
                sgr += ';1'
            if cell['underline']:
                sgr += ';4'
            if cell['reverse']:
                sgr += ';7'

            fg = cell['fg']
            if isinstance(fg, list):
                sgr += f';38;2;{fg[0]};{fg[1]};{fg[2]}'
            elif isinstance(fg, int) and fg > 7:
                sgr += f';38;5;{fg}'
            elif isinstance(fg, int):
                sgr += f';{30 + fg}'

            bg = cell['bg']
            if isinstance(bg, list):
                sgr += f';48;2;{bg[0]};{bg[1]};{bg[2]}'
            elif isinstance(bg, int) and bg > 7:
                sgr += f';48;5;{bg}'
            elif isinstance(bg, int):
                sgr += f';{40 + bg}'

            sgr += 'm'
            output.extend(sgr.encode())
            output.extend(cell['char'].encode())

    cr = after_snap['cursor']['row']
    cc = after_snap['cursor']['col']
    output.extend(f'\x1b[{cr + 1};{cc + 1}H'.encode())
    output.extend(b'\x1b[0m')

    return bytes(output)
