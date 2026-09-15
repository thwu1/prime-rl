#!/usr/bin/env python3
"""
NES PPU background tile rendering pipeline.

Drives the PPU scroll register state machine through a register trace,
renders 256x240 background tiles following NES PPU rendering semantics:
  - Pre-render: process initial register writes, copy_vertical
  - Per scanline: apply mid-frame writes, copy_horizontal, render tiles
    using v register, increment_y

Tile rendering:
  - 2bpp CHR bitplane decoding (high byte = bit 1, low byte = bit 0)
  - Nametable tile fetch using coarse X/Y from v register
  - Attribute table palette quadrant selection
  - Vertical mirroring: physical nametable = nt_h (bit 10 of v)
  - Fine X scroll for sub-tile horizontal offset
"""


import json
import os
import sys

sys.path.insert(0, '/app')
from ppu_scroll import PPUScrollState


def process_op(ppu, op):
    """Apply a single PPU register operation."""
    name = op[0]
    if name == 'ppustatus':
        ppu.read_ppustatus()
    elif name == 'ppuscroll':
        ppu.write_ppuscroll(op[1])
    elif name == 'ppuaddr':
        ppu.write_ppuaddr(op[1])
    elif name == 'ppuctrl':
        ppu.write_ppuctrl(op[1])


def resolve_nt(nt_h, nt_v, mirroring):
    """Map logical nametable to physical index based on mirroring."""
    if mirroring == "vertical":
        return nt_h
    return nt_v


def render_scanline(ppu, chr_rom, vram, palette, mirroring, fb, scanline,
                    pat_base):
    """Render one scanline (256 pixels) of background tiles using v."""
    fine_x = ppu.x
    pixel = 0
    start_bit = fine_x

    while pixel < 256:
        # Extract scroll components from current v register
        fine_y = (ppu.v >> 12) & 7
        nt_v = (ppu.v >> 11) & 1
        nt_h = (ppu.v >> 10) & 1
        coarse_y = (ppu.v >> 5) & 0x1F
        coarse_x = ppu.v & 0x1F

        # Resolve physical nametable from mirroring mode
        phys = resolve_nt(nt_h, nt_v, mirroring)

        # Fetch tile index from nametable
        tile_idx = vram[phys * 1024 + coarse_y * 32 + coarse_x]

        # Fetch attribute byte and extract 2-bit palette selector
        attr_idx = (coarse_y >> 2) * 8 + (coarse_x >> 2)
        attr_byte = vram[phys * 1024 + 960 + attr_idx]
        shift = ((coarse_y & 2) << 1) | (coarse_x & 2)
        pal_num = (attr_byte >> shift) & 3

        # Decode 2bpp tile row from CHR ROM
        tile_addr = pat_base + tile_idx * 16
        lo = chr_rom[tile_addr + fine_y]
        hi = chr_rom[tile_addr + 8 + fine_y]

        # Output pixels for this tile
        for b in range(start_bit, 8):
            if pixel >= 256:
                break
            sa = 7 - b
            color = ((hi >> sa) & 1) << 1 | ((lo >> sa) & 1)
            if color == 0:
                fb[scanline * 256 + pixel] = palette[0]
            else:
                fb[scanline * 256 + pixel] = palette[pal_num * 4 + color]
            pixel += 1

        start_bit = 0

        # Increment coarse X in v with nametable wrapping
        ppu.increment_coarse_x()


def main():
    # Read binary PPU data
    with open('/app/chr_rom.bin', 'rb') as f:
        chr_rom = f.read()
    with open('/app/vram.bin', 'rb') as f:
        vram = f.read()
    with open('/app/palette.bin', 'rb') as f:
        palette = f.read()
    with open('/app/register_trace.json') as f:
        trace = json.load(f)

    mirroring = trace['mirroring']
    pat_base = trace['pattern_table'] * 0x1000

    ppu = PPUScrollState()

    # Process initial register writes (VBlank setup)
    for op in trace['initial_ops']:
        process_op(ppu, op)

    # Pre-render: copy vertical scroll bits from t to v
    ppu.copy_vertical()

    fb = bytearray(256 * 240)

    for scanline in range(240):
        # Apply mid-frame register writes for this scanline
        key = str(scanline)
        if key in trace['scanline_ops']:
            for op in trace['scanline_ops'][key]:
                process_op(ppu, op)

        # Copy horizontal scroll bits from t to v
        ppu.copy_horizontal()

        # Render 256 pixels of background
        render_scanline(ppu, chr_rom, vram, palette, mirroring, fb, scanline,
                        pat_base)

        # Increment Y position in v
        ppu.increment_y()

    # Write output framebuffer
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/frame.bin', 'wb') as f:
        f.write(fb)

    print(f"Wrote {len(fb)} bytes to /app/output/frame.bin")


if __name__ == '__main__':
    main()
