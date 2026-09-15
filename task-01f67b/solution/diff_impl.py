"""
Solution: terminal screen diff engine.

Implements compute_diff(prev, curr) with:
  - Row/cell scanning with unchanged-region skipping
  - Optimal cursor-movement selection (CUP vs relative vs CR)
  - Incremental SGR attribute tracking (reset-vs-incremental choice)
  - Erase-to-end-of-line (EL) optimisation

"""

from terminal import Screen, Cell, Attrs


def compute_diff(prev: Screen, curr: Screen) -> bytes:
    out = bytearray()
    rows = curr.rows
    cols = curr.cols

    cr = prev.cursor_row
    cc = prev.cursor_col
    attrs = Attrs()  # parser starts with default drawing attrs

    for r in range(rows):
        # ---- quick check: any changes in this row? ----
        prev_row = prev.cells[r]
        curr_row = curr.cells[r]
        first_change = -1
        for c in range(cols):
            if prev_row[c] != curr_row[c]:
                first_change = c
                break
        if first_change < 0:
            continue

        # find last changed cell
        last_change = first_change
        for c in range(cols - 1, first_change, -1):
            if prev_row[c] != curr_row[c]:
                last_change = c
                break

        c = first_change
        while c <= last_change:
            if prev_row[c] == curr_row[c]:
                c += 1
                continue

            # --- check EL opportunity: all cells from c..end are spaces
            #     with the same attrs in curr, and at least one differs from prev
            el_attrs = curr_row[c].attrs
            can_el = True
            for ec in range(c, cols):
                cell = curr_row[ec]
                if cell.char != ' ' or cell.attrs != el_attrs:
                    can_el = False
                    break
            if can_el:
                # all cells from c to end-of-row are spaces with el_attrs
                # check that at least some of them actually differ
                any_diff = False
                for ec in range(c, cols):
                    if prev_row[ec] != curr_row[ec]:
                        any_diff = True
                        break
                if any_diff:
                    out += _move(cr, cc, r, c, cols)
                    cr, cc = r, c
                    if attrs != el_attrs:
                        out += _sgr(attrs, el_attrs)
                        attrs = el_attrs
                    out += b'\x1b[K'
                    break  # done with this row

            # --- position cursor ---
            if cr != r or cc != c:
                out += _move(cr, cc, r, c, cols)
                cr, cc = r, c

            # --- set attributes ---
            target_attrs = curr_row[c].attrs
            if target_attrs != attrs:
                out += _sgr(attrs, target_attrs)
                attrs = target_attrs

            # --- write character ---
            out += curr_row[c].char.encode('ascii')
            cc += 1
            c += 1

    # --- final cursor positioning ---
    if cr != curr.cursor_row or cc != curr.cursor_col:
        out += _move(cr, cc, curr.cursor_row, curr.cursor_col, cols)

    return bytes(out)


# ---------------------------------------------------------------------------
# Cursor movement optimiser
# ---------------------------------------------------------------------------

def _move(fr: int, fc: int, tr: int, tc: int, cols: int) -> bytes:
    """Return shortest escape sequence to move cursor from (fr,fc) to (tr,tc)."""
    if fr == tr and fc == tc:
        return b''

    options = []

    # Option 1 — CUP (absolute)
    if tr == 0 and tc == 0:
        options.append(b'\x1b[H')
    else:
        options.append(f'\x1b[{tr + 1};{tc + 1}H'.encode())

    # Option 2 — relative vertical + horizontal
    rel = bytearray()
    dr = tr - fr
    dc = tc - fc
    if dr != 0:
        if dr == 1:
            rel += b'\x1b[B'
        elif dr == -1:
            rel += b'\x1b[A'
        elif dr > 1:
            rel += f'\x1b[{dr}B'.encode()
        else:
            rel += f'\x1b[{-dr}A'.encode()
    if dc != 0:
        if dc == 1:
            rel += b'\x1b[C'
        elif dc == -1:
            rel += b'\x1b[D'
        elif dc > 1:
            rel += f'\x1b[{dc}C'.encode()
        else:
            rel += f'\x1b[{-dc}D'.encode()
    if rel:
        options.append(bytes(rel))

    # Option 3 — CR (+ optional CUF) for same-row leftward jumps
    if fr == tr:
        cr = bytearray(b'\r')
        if tc > 0:
            if tc == 1:
                cr += b'\x1b[C'
            else:
                cr += f'\x1b[{tc}C'.encode()
        options.append(bytes(cr))

    # Option 4 — LF for next-row (same column or with horizontal adjust)
    if dr == 1 and fc <= cols - 1:
        lf = bytearray(b'\n')
        if fc != tc:
            # need horizontal adjustment after LF (col unchanged by LF)
            hdc = tc - fc
            if hdc > 0:
                if hdc == 1:
                    lf += b'\x1b[C'
                else:
                    lf += f'\x1b[{hdc}C'.encode()
            elif hdc < 0:
                # going left: CR + CUF might be shorter
                lf2 = bytearray(b'\n\r')
                if tc > 0:
                    if tc == 1:
                        lf2 += b'\x1b[C'
                    else:
                        lf2 += f'\x1b[{tc}C'.encode()
                options.append(bytes(lf2))
                if hdc == -1:
                    lf += b'\x1b[D'
                else:
                    lf += f'\x1b[{-hdc}D'.encode()
        options.append(bytes(lf))

    return min(options, key=len)


# ---------------------------------------------------------------------------
# SGR attribute diff
# ---------------------------------------------------------------------------

def _sgr(current: Attrs, target: Attrs) -> bytes:
    """Minimal SGR transition from *current* to *target*."""
    if current == target:
        return b''

    # Incremental params
    inc = []
    if current.bold != target.bold:
        inc.append(1 if target.bold else 22)
    if current.italic != target.italic:
        inc.append(3 if target.italic else 23)
    if current.underline != target.underline:
        inc.append(4 if target.underline else 24)
    if current.inverse != target.inverse:
        inc.append(7 if target.inverse else 27)
    if current.fg != target.fg:
        inc.extend(_cparam(target.fg, True))
    if current.bg != target.bg:
        inc.extend(_cparam(target.bg, False))

    # Reset-and-rebuild params
    rst = [0]
    if target.bold:
        rst.append(1)
    if target.italic:
        rst.append(3)
    if target.underline:
        rst.append(4)
    if target.inverse:
        rst.append(7)
    if target.fg != -1:
        rst.extend(_cparam(target.fg, True))
    if target.bg != -1:
        rst.extend(_cparam(target.bg, False))

    inc_s = ';'.join(str(p) for p in inc) if inc else ''
    rst_s = ';'.join(str(p) for p in rst)
    inc_b = f'\x1b[{inc_s}m'.encode() if inc_s else b''
    rst_b = f'\x1b[{rst_s}m'.encode()

    if not inc_b:
        return rst_b
    return inc_b if len(inc_b) <= len(rst_b) else rst_b


def _cparam(color: int, fg: bool) -> list:
    if color == -1:
        return [39 if fg else 49]
    base = 30 if fg else 40
    if 0 <= color <= 7:
        return [base + color]
    if 8 <= color <= 15:
        return [base + 60 + color - 8]
    return [base + 8, 5, color]
