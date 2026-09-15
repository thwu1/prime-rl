#!/usr/bin/env python3
"""
Fix all 5 bugs in /app/ppu_scroll.py to match NES PPU hardware specification.

Bug 1 (increment_y): Toggles horizontal nametable bit 10 (0x0400) instead of
       vertical nametable bit 11 (0x0800) when coarse Y wraps at row 29.

Bug 2 (write_ppuaddr): First $2006 write uses mask ~0x3F00 which only clears
       bits 13-8, leaving bit 14 of t intact. Should clear bits 14-8 entirely
       so that stale fine Y data from previous $2005 writes is removed.

Bug 3 (write_ppuscroll): Second $2005 write uses mask ~0x03E0 which only clears
       coarse Y (bits 9-5), leaving fine Y (bits 14-12) stale from any prior
       operation. Should use ~0x73E0 to clear both fine Y and coarse Y.

Bug 4 (copy_horizontal): Uses mask 0x001F (coarse X only) instead of 0x041F
       which also includes horizontal nametable bit 10. At dot 257 of each
       scanline, both coarse X and the horizontal nametable select must be
       reloaded from t.

Bug 5 (get_attribute_address): The shift amounts for extracting the high 3 bits
       of coarse X and coarse Y from v are swapped. (v>>4)&0x38 should extract
       coarse Y's high bits, and (v>>2)&0x07 should extract coarse X's high bits.
"""


with open('/app/ppu_scroll.py', 'r') as f:
    src = f.read()

# Bug 1: increment_y - wrong nametable bit
src = src.replace(
    'self.v ^= 0x0400                    # switch nametable vertically',
    'self.v ^= 0x0800                    # switch nametable vertically',
)

# Bug 2: write_ppuaddr first write - bit 14 not cleared
src = src.replace(
    'self.t = (self.t & ~0x3F00) | ((data & 0x3F) << 8)',
    'self.t = (self.t & 0x00FF) | ((data & 0x3F) << 8)',
)

# Bug 3: write_ppuscroll second write - fine Y not cleared
src = src.replace(
    'self.t = (self.t & ~0x03E0)',
    'self.t = (self.t & ~0x73E0)',
)

# Bug 4: copy_horizontal - missing nametable bit
src = src.replace(
    'self.v = (self.v & ~0x001F) | (self.t & 0x001F)',
    'self.v = (self.v & ~0x041F) | (self.t & 0x041F)',
)

# Bug 5: get_attribute_address - swapped shift amounts
src = src.replace(
    '| ((self.v >> 2) & 0x38)\n                | ((self.v >> 4) & 0x07))',
    '| ((self.v >> 4) & 0x38)\n                | ((self.v >> 2) & 0x07))',
)

with open('/app/ppu_scroll.py', 'w') as f:
    f.write(src)

print("Fixed all 5 bugs in ppu_scroll.py")
