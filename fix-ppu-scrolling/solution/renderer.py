#!/usr/bin/env python3
"""
NES PPU background tile renderer.

Reads binary CHR ROM, VRAM, and palette dumps plus a rendering
configuration, and produces a pixel-accurate 256x240 framebuffer.

Implements the NES PPU's background rendering pipeline:
- 2bpp CHR tile decoding (interleaved bitplanes)
- Nametable tile index lookup
- Attribute table 2-bit palette quadrant selection
- v/t/x scroll register state machine
- Coarse X increment with horizontal nametable wrapping
- Y increment with row-29 nametable toggle and row-31 wrap
- Vertical mirroring of nametable addresses
- Mid-frame scroll region transitions
"""


import json
import os


def resolve_nametable(nt_h, nt_v, mirroring):
    """Map logical nametable (nt_h, nt_v) to physical index (0 or 1).

    Vertical mirroring: NT0=NT2=phys0, NT1=NT3=phys1
    Horizontal mirroring: NT0=NT1=phys0, NT2=NT3=phys1
    """
    nt = (nt_v << 1) | nt_h
    if mirroring == "vertical":
        return nt & 1
    elif mirroring == "horizontal":
        return (nt >> 1) & 1
    return nt  # four-screen


def increment_y(v):
    """Increment the Y position in the v register.

    Fine Y (bits 14-12) increments first. On overflow past 7,
    coarse Y (bits 9-5) increments. At coarse Y == 29, it wraps
    to 0 and toggles the vertical nametable bit. At coarse Y == 31,
    it wraps to 0 without toggling.
    """
    if (v & 0x7000) != 0x7000:
        v += 0x1000
    else:
        v &= ~0x7000  # fine Y = 0
        y = (v & 0x03E0) >> 5
        if y == 29:
            y = 0
            v ^= 0x0800  # toggle vertical nametable
        elif y == 31:
            y = 0  # wrap without toggle
        else:
            y += 1
        v = (v & ~0x03E0) | (y << 5)
    return v


def scroll_to_v(scroll_x, scroll_y):
    """Convert 9-bit scroll coordinates to v register and fine_x.

    v register layout (15 bits):
        yyy NN YYYYY XXXXX
        ||| || ||||| +++++-- coarse X scroll (bits 4-0)
        ||| || +++++-------- coarse Y scroll (bits 9-5)
        ||| ++-------------- nametable select (bits 11-10)
        +++----------------- fine Y scroll (bits 14-12)
    """
    fine_x = scroll_x & 7
    coarse_x = (scroll_x >> 3) & 0x1F
    nt_h = (scroll_x >> 8) & 1

    fine_y = scroll_y & 7
    coarse_y = (scroll_y >> 3) & 0x1F
    nt_v = (scroll_y >> 8) & 1

    v = ((fine_y << 12) | (nt_v << 11) | (nt_h << 10)
         | (coarse_y << 5) | coarse_x)
    return v, fine_x


def render_scanline(v, fine_x, chr_rom, vram, palette, mirroring, pat_base):
    """Render one scanline (256 pixels) of background tiles.

    Returns a bytearray of 256 palette color indices.
    """
    pixels = bytearray(256)

    fine_y = (v >> 12) & 7
    nt_v = (v >> 11) & 1
    coarse_y = (v >> 5) & 0x1F
    coarse_x = v & 0x1F
    nt_h = (v >> 10) & 1

    pixel_out = 0
    start_bit = fine_x

    while pixel_out < 256:
        # Resolve physical nametable from mirroring mode
        phys_nt = resolve_nametable(nt_h, nt_v, mirroring)

        # Fetch tile index from nametable
        # Note: when coarse_y >= 30, this reads from the attribute table
        # area of the nametable (the "negative scroll" effect)
        tile_idx = vram[phys_nt * 1024 + coarse_y * 32 + coarse_x]

        # Fetch attribute byte and extract 2-bit palette selector
        # Each attribute byte covers a 4x4 tile area (32x32 pixels)
        # Quadrants: TL=bits 1:0, TR=bits 3:2, BL=bits 5:4, BR=bits 7:6
        attr_byte_idx = (coarse_y >> 2) * 8 + (coarse_x >> 2)
        attr_byte = vram[phys_nt * 1024 + 960 + attr_byte_idx]
        shift = ((coarse_y & 2) << 1) | (coarse_x & 2)
        pal_num = (attr_byte >> shift) & 3

        # Decode tile row from CHR ROM (2bpp format)
        tile_addr = pat_base + tile_idx * 16
        lo_byte = chr_rom[tile_addr + fine_y]
        hi_byte = chr_rom[tile_addr + 8 + fine_y]

        # Output pixels from this tile
        for bit_pos in range(start_bit, 8):
            if pixel_out >= 256:
                break
            shift_amt = 7 - bit_pos
            lo_bit = (lo_byte >> shift_amt) & 1
            hi_bit = (hi_byte >> shift_amt) & 1
            color = (hi_bit << 1) | lo_bit

            if color == 0:
                # Transparent pixel -> backdrop color
                pixels[pixel_out] = palette[0]
            else:
                pixels[pixel_out] = palette[pal_num * 4 + color]
            pixel_out += 1

        start_bit = 0  # subsequent tiles start from bit 0

        # Increment coarse X with nametable wrapping
        coarse_x += 1
        if coarse_x > 31:
            coarse_x = 0
            nt_h ^= 1  # toggle horizontal nametable

    return pixels


def render_frame(chr_rom, vram, palette, config):
    """Render a complete 256x240 frame from the given configuration."""
    framebuffer = bytearray(256 * 240)
    mirroring = config['mirroring']
    pat_base = config['pattern_table_base']

    for region in config['frames'][0]['scroll_regions']:
        start_sl = region['start_scanline']
        end_sl = region['end_scanline']
        v, fine_x = scroll_to_v(region['scroll_x'], region['scroll_y'])

        for scanline in range(start_sl, end_sl + 1):
            row = render_scanline(
                v, fine_x, chr_rom, vram, palette, mirroring, pat_base)
            framebuffer[scanline * 256:(scanline + 1) * 256] = row
            v = increment_y(v)

    return bytes(framebuffer)


def main():
    # Read input data
    with open('/app/chr_rom.bin', 'rb') as f:
        chr_rom = f.read()
    with open('/app/vram.bin', 'rb') as f:
        vram = f.read()
    with open('/app/palette.bin', 'rb') as f:
        palette = f.read()
    with open('/app/render_config.json', 'r') as f:
        config = json.load(f)

    # Render the frame
    framebuffer = render_frame(chr_rom, vram, palette, config)

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/frame_0.bin', 'wb') as f:
        f.write(framebuffer)

    print(f"Rendered frame_0.bin ({len(framebuffer)} bytes)")


if __name__ == '__main__':
    main()
