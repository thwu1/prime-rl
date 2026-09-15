"""
Fix the 5 conformance bugs in /app/vtbuffer.py by reading the source,
identifying the violations, and writing the corrected implementation.
"""
import re

with open("/app/vtbuffer.py", "r") as f:
    source = f.read()

# ============================================================
# Bug 1: DECCRA copies in-place without a temporary buffer.
# DEC VT420 spec requires overlapping copies to behave as if
# copied through an intermediate buffer. Fix: snapshot source
# cells before writing to destination.
# ============================================================

old_deccra_body = '''        src_h = sb - st + 1
        src_w = sr - sl + 1

        for r in range(src_h):
            for c in range(src_w):
                ar = st + r
                ac = sl + c
                dr = dt + r
                dc = dl + c
                if 1 <= dr <= self._height and 1 <= dc <= self._width:
                    if 1 <= ar <= self._height and 1 <= ac <= self._width:
                        src_cell = self._grid[ar - 1][ac - 1]
                        dst_cell = self._grid[dr - 1][dc - 1]
                        dst_cell.char = src_cell.char
                        dst_cell.protected = src_cell.protected'''

new_deccra_body = '''        src_h = sb - st + 1
        src_w = sr - sl + 1

        # Copy source into temp buffer to handle overlapping regions
        tmp = []
        for r in range(src_h):
            row = []
            for c in range(src_w):
                ar = st + r
                ac = sl + c
                if 1 <= ar <= self._height and 1 <= ac <= self._width:
                    cell = self._grid[ar - 1][ac - 1]
                    row.append((cell.char, cell.protected))
                else:
                    row.append(('\\x00', 0))
            tmp.append(row)

        # Paste from temp buffer, clipping destination
        for r in range(src_h):
            for c in range(src_w):
                dr = dt + r
                dc = dl + c
                if 1 <= dr <= self._height and 1 <= dc <= self._width:
                    cell = self._grid[dr - 1][dc - 1]
                    cell.char = tmp[r][c][0]
                    cell.protected = tmp[r][c][1]'''

assert old_deccra_body in source, "Could not find DECCRA in-place copy pattern"
source = source.replace(old_deccra_body, new_deccra_body)

# ============================================================
# Bug 2: DECSERA uses 'if not cell.protected' which treats both
# DEC (1) and ISO (2) protection as protective. DEC VT420 spec
# says DECSERA only respects DEC protection (mode 1), not ISO.
# Fix: change to 'if cell.protected != 1'.
# ============================================================

old_decsera_check = "                if not cell.protected:"
new_decsera_check = "                if cell.protected != 1:  # Only DEC protection (1) is respected"

assert old_decsera_check in source, "Could not find DECSERA protection check"
source = source.replace(old_decsera_check, new_decsera_check)

# ============================================================
# Bug 3: DECFRA does not call _translate_coords, so origin mode
# is completely ignored. DEC VT420 spec requires DECFRA to
# respect origin mode for coordinate translation.
# Fix: call _translate_coords like other rect operations.
# ============================================================

old_decfra = '''    def decfra(self, ch_code, top, left, bottom, right):
        t = top if top is not None else 1
        l = left if left is not None else 1
        b = bottom if bottom is not None else self._height
        r = right if right is not None else self._width
        t, l, b, r = self._clip_rect(t, l, b, r)'''

new_decfra = '''    def decfra(self, ch_code, top, left, bottom, right):
        t, l, b, r = self._translate_coords(top, left, bottom, right)
        t, l, b, r = self._clip_rect(t, l, b, r)'''

assert old_decfra in source, "Could not find DECFRA coord handling"
source = source.replace(old_decfra, new_decfra)

# ============================================================
# Bug 4: set_scrolling_region does not reset cursor to (1,1).
# DEC VT420 spec (confirmed by esctest2 test_DECSTBM_MovsCursorToOrigin)
# requires cursor to move to (1,1) whenever DECSTBM is issued.
# Fix: add cursor reset at end of set_scrolling_region.
# ============================================================

# Find the end of set_scrolling_region method - it ends before set_left_right_margins
old_scrolling_end = '''            else:
                self._scroll_top = 1
                self._scroll_bottom = self._height

    def set_left_right_margins'''

new_scrolling_end = '''            else:
                self._scroll_top = 1
                self._scroll_bottom = self._height
        self._cursor_row = 1
        self._cursor_col = 1

    def set_left_right_margins'''

assert old_scrolling_end in source, "Could not find scrolling region method end"
source = source.replace(old_scrolling_end, new_scrolling_end)

# ============================================================
# Bug 5: DECERA incorrectly checks character protection.
# DEC VT420 spec says DECERA ignores protection entirely --
# it erases all cells unconditionally. Only DECSERA is selective.
# Fix: remove the protection check.
# ============================================================

old_decera_loop = '''        for row in range(t, b + 1):
            for col in range(l, r + 1):
                cell = self._grid[row - 1][col - 1]
                if cell.protected != 1:
                    cell.char = '\\x00'
                    cell.protected = 0'''

new_decera_loop = '''        for row in range(t, b + 1):
            for col in range(l, r + 1):
                cell = self._grid[row - 1][col - 1]
                cell.char = '\\x00'
                cell.protected = 0'''

# DECERA loop is the first occurrence; DECSERA loop is different
assert old_decera_loop in source, "Could not find DECERA protection check"
source = source.replace(old_decera_loop, new_decera_loop, 1)

# Write the fixed file
with open("/app/vtbuffer.py", "w") as f:
    f.write(source)

print("All 5 conformance bugs fixed in /app/vtbuffer.py")

# Verify the fixes
import subprocess
result = subprocess.run(
    ["python3", "-c", "from vtbuffer import ScreenBuffer; print('Import OK')"],
    cwd="/app", capture_output=True, text=True
)
print(result.stdout.strip())
if result.returncode != 0:
    print("ERROR:", result.stderr)
    exit(1)
