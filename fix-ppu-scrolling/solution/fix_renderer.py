#!/usr/bin/env python3
"""Fix 4 bugs in /app/renderer.c to match NES PPU hardware specification.

Bug 1 (resolve_nt): Vertical mirroring returns (nt >> 1) & 1 (which is nt_v)
       instead of nt & 1 (which is nt_h). Vertical mirroring means NT0 and NT2
       map to physical bank 0, NT1 and NT3 to bank 1 — selected by horizontal bit.

Bug 2 (inc_y): At coarse Y == 31, the code toggles vertical nametable
       (v ^= 0x0800). Y==31 is in the attribute table area; it should wrap
       to 0 without toggling, unlike Y==29 which is the last tile row.

Bug 3 (do_scanline): Bitplane combination order is (lb << 1) | hb, which swaps
       the high and low bitplane contributions. Correct order is (hb << 1) | lb
       where the high bitplane contributes bit 1 of the 2-bit color index.

Bug 4 (do_scanline): Attribute quadrant shift uses (cy & 2) | (cx & 2) which
       collapses the 4-quadrant selection to 3 values. Correct formula is
       ((cy & 2) << 1) | (cx & 2), giving shifts 0, 2, 4, 6 for the four
       quadrants TL, TR, BL, BR.
"""


with open('/app/renderer.c', 'r') as f:
    src = f.read()

# Bug 1: resolve_nt - vertical mirroring should use nt_h (nt & 1)
src = src.replace(
    '    if (strcmp(mir, "vertical") == 0)\n        return (nt >> 1) & 1;',
    '    if (strcmp(mir, "vertical") == 0)\n        return nt & 1;',
)

# Bug 2: inc_y - y==31 should NOT toggle nametable
src = src.replace(
    '} else if (y == 31) {\n            y = 0;\n            v ^= 0x0800;\n        } else {',
    '} else if (y == 31) {\n            y = 0;\n        } else {',
)

# Bug 3: do_scanline - bitplane order should be (hb << 1) | lb
src = src.replace(
    'int c  = (lb << 1) | hb;',
    'int c  = (hb << 1) | lb;',
)

# Bug 4: do_scanline - attribute shift needs << 1 on cy
src = src.replace(
    'int sh = (cy & 2) | (cx & 2);',
    'int sh = ((cy & 2) << 1) | (cx & 2);',
)

with open('/app/renderer.c', 'w') as f:
    f.write(src)

print("Fixed all 4 bugs in renderer.c")
