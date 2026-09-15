#!/usr/bin/env python3
"""Generate NES PPU rendering task data and reference checksums.

Creates binary PPU memory dumps, a register trace for split-scrolling,
and a JSON reference file with per-scanline checksums for verification.

Uses a correct PPU state machine (embedded) to produce golden-reference output.
"""


import json
import hashlib
import zlib
import os


# ---- Correct PPU state machine (reference, NOT deployed to /app) ----

class CorrectPPUState:
    """Correct PPU scroll register state machine for reference rendering."""

    def __init__(self):
        self.v = 0
        self.t = 0
        self.x = 0
        self.w = 0
        self.ppuctrl = 0

    def write_ppuctrl(self, data):
        self.t = (self.t & ~0x0C00) | ((data & 0x03) << 10)
        self.ppuctrl = data

    def read_ppustatus(self):
        self.w = 0

    def write_ppuscroll(self, data):
        if self.w == 0:
            self.t = (self.t & ~0x001F) | ((data >> 3) & 0x1F)
            self.x = data & 0x07
            self.w = 1
        else:
            self.t = (self.t & ~0x73E0)
            self.t |= ((data & 0x07) << 12)
            self.t |= (((data >> 3) & 0x1F) << 5)
            self.w = 0

    def write_ppuaddr(self, data):
        if self.w == 0:
            self.t = (self.t & 0x00FF) | ((data & 0x3F) << 8)
            self.w = 1
        else:
            self.t = (self.t & 0xFF00) | (data & 0xFF)
            self.v = self.t
            self.w = 0

    def increment_coarse_x(self):
        if (self.v & 0x001F) == 31:
            self.v &= ~0x001F
            self.v ^= 0x0400
        else:
            self.v += 1

    def increment_y(self):
        if (self.v & 0x7000) != 0x7000:
            self.v += 0x1000
        else:
            self.v &= ~0x7000
            y = (self.v & 0x03E0) >> 5
            if y == 29:
                y = 0
                self.v ^= 0x0800
            elif y == 31:
                y = 0
            else:
                y += 1
            self.v = (self.v & ~0x03E0) | (y << 5)

    def copy_horizontal(self):
        self.v = (self.v & ~0x041F) | (self.t & 0x041F)

    def copy_vertical(self):
        self.v = (self.v & ~0x7BE0) | (self.t & 0x7BE0)


# ---- Rendering pipeline (reference) ----

def process_op(ppu, op):
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
    if mirroring == "vertical":
        return nt_h
    return nt_v


def render_scanline(ppu, chr_rom, vram, palette, mirroring, fb, scanline,
                    pat_base):
    fine_x = ppu.x
    pixel = 0
    start_bit = fine_x

    while pixel < 256:
        fine_y = (ppu.v >> 12) & 7
        nt_v = (ppu.v >> 11) & 1
        nt_h = (ppu.v >> 10) & 1
        coarse_y = (ppu.v >> 5) & 0x1F
        coarse_x = ppu.v & 0x1F

        phys = resolve_nt(nt_h, nt_v, mirroring)
        tile_idx = vram[phys * 1024 + coarse_y * 32 + coarse_x]

        attr_idx = (coarse_y >> 2) * 8 + (coarse_x >> 2)
        attr_byte = vram[phys * 1024 + 960 + attr_idx]
        shift = ((coarse_y & 2) << 1) | (coarse_x & 2)
        pal_num = (attr_byte >> shift) & 3

        tile_addr = pat_base + tile_idx * 16
        lo = chr_rom[tile_addr + fine_y]
        hi = chr_rom[tile_addr + 8 + fine_y]

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
        ppu.increment_coarse_x()


def render_frame(chr_rom, vram, palette, trace):
    ppu = CorrectPPUState()
    mirroring = trace['mirroring']
    pat_base = trace['pattern_table'] * 0x1000

    for op in trace['initial_ops']:
        process_op(ppu, op)

    ppu.copy_vertical()

    fb = bytearray(256 * 240)

    for scanline in range(240):
        key = str(scanline)
        if key in trace['scanline_ops']:
            for op in trace['scanline_ops'][key]:
                process_op(ppu, op)

        ppu.copy_horizontal()

        render_scanline(ppu, chr_rom, vram, palette, mirroring, fb, scanline,
                        pat_base)

        ppu.increment_y()

    return bytes(fb)


# ---- Data generation ----

def gen_chr():
    """Generate 4096 bytes of CHR ROM (256 tiles in NES 2bpp format)."""
    d = bytearray(4096)
    for r in range(8):
        d[16 + r] = 0xFF
        d[16 + 8 + r] = 0xFF
    for r in range(8):
        d[32 + r] = 0xFF if r % 2 == 0 else 0x00
    for r in range(8):
        d[48 + 8 + r] = 0xAA
    for r in range(8):
        p = 0xAA if r % 2 == 0 else 0x55
        d[64 + r] = p
        d[64 + 8 + r] = p
    for r in range(8):
        d[80 + r] = 1 << (7 - r)
    for t in range(6, 256):
        s = t * 7 + 13
        for r in range(8):
            d[t * 16 + r] = (s + r * 31) & 0xFF
            d[t * 16 + 8 + r] = (s + r * 17 + 5) & 0xFF
    return bytes(d)


def gen_vram():
    """Generate 2048 bytes: 2 nametables (960 tile indices + 64 attr each)."""
    d = bytearray(2048)
    for y in range(30):
        for x in range(32):
            d[y * 32 + x] = (y * 32 + x) % 256
    for i in range(64):
        r, c = i // 8, i % 8
        tl = (r + c) % 4
        tr = (r + c + 1) % 4
        bl = (r + c + 2) % 4
        br = (r + c + 3) % 4
        d[960 + i] = tl | (tr << 2) | (bl << 4) | (br << 6)
    for y in range(30):
        for x in range(32):
            d[1024 + y * 32 + x] = ((y + 5) * 32 + (x + 10)) % 256
    for i in range(64):
        r, c = i // 8, i % 8
        tl = (r * 2 + c) % 4
        tr = (r * 2 + c + 1) % 4
        bl = (r * 2 + c + 2) % 4
        br = (r * 2 + c + 3) % 4
        d[1024 + 960 + i] = tl | (tr << 2) | (bl << 4) | (br << 6)
    return bytes(d)


def gen_palette():
    """Generate 32 bytes of palette data (16 BG + 16 sprite)."""
    p = bytearray(32)
    p[0] = 0x0F; p[1] = 0x00; p[2] = 0x10; p[3] = 0x30
    p[4] = 0x0F; p[5] = 0x01; p[6] = 0x11; p[7] = 0x21
    p[8] = 0x0F; p[9] = 0x06; p[10] = 0x16; p[11] = 0x26
    p[12] = 0x0F; p[13] = 0x09; p[14] = 0x19; p[15] = 0x29
    for i in range(16, 32):
        p[i] = (i + 0x10) & 0x3F
    return bytes(p)


if __name__ == '__main__':
    os.makedirs('/app/output', exist_ok=True)

    chr_rom = gen_chr()
    vram = gen_vram()
    palette = gen_palette()

    # Register trace: four split-scroll regions exercising different PPU
    # register write mechanisms and edge cases.
    #
    # Region 1 (scanlines 0-79): initial scroll via $2005/$2000
    # Region 2 (scanlines 80-159): mid-frame X change via $2005, Y from
    #   increment chain; ppuctrl sets nt_h=1 to exercise copy_horizontal
    # Region 3 (scanlines 160-207): full scroll change via $2006; exercises
    #   $2006 first-write bit-14 clearing (interacts with prior $2005 fineY)
    # Region 4 (scanlines 208-239): $2006 sets coarseY=28 to exercise
    #   Y-wrap at row 29 with nametable toggle
    trace = {
        "initial_ops": [
            ["ppustatus"],
            ["ppuscroll", 125],
            ["ppuscroll", 13],
            ["ppuctrl", 0]
        ],
        "scanline_ops": {
            "80": [
                ["ppustatus"],
                ["ppuscroll", 4],
                ["ppuscroll", 36],
                ["ppuctrl", 1]
            ],
            "160": [
                ["ppustatus"],
                ["ppuaddr", 42],
                ["ppuaddr", 205]
            ],
            "208": [
                ["ppustatus"],
                ["ppuaddr", 3],
                ["ppuaddr", 128]
            ]
        },
        "mirroring": "vertical",
        "pattern_table": 0
    }

    with open('/app/chr_rom.bin', 'wb') as f:
        f.write(chr_rom)
    with open('/app/vram.bin', 'wb') as f:
        f.write(vram)
    with open('/app/palette.bin', 'wb') as f:
        f.write(palette)

    with open('/app/register_trace.json', 'w') as f:
        json.dump(trace, f, indent=2)

    fb = render_frame(chr_rom, vram, palette, trace)

    ref = {
        "frame_sha256": hashlib.sha256(fb).hexdigest(),
        "frame_size": len(fb),
        "scanline_crc32": {},
    }
    for sl in range(240):
        ref["scanline_crc32"][str(sl)] = (
            zlib.crc32(fb[sl * 256:(sl + 1) * 256]) & 0xFFFFFFFF
        )

    coords = [
        (0, 0), (127, 0), (255, 0),
        (0, 39), (200, 50),
        (128, 79), (255, 79),
        (0, 80), (128, 80),
        (50, 120), (200, 140),
        (0, 159), (255, 159),
        (0, 160), (128, 175),
        (100, 190), (255, 207),
        (0, 208), (128, 208),
        (50, 220), (128, 224),
        (0, 230), (200, 235),
        (255, 239),
    ]
    ref["spot_checks"] = [
        {"x": x, "y": y, "value": fb[y * 256 + x]} for x, y in coords
    ]

    with open('/app/reference.json', 'w') as f:
        json.dump(ref, f, indent=2)

    print(f"Generated reference. SHA-256: {ref['frame_sha256']}")
    print(f"Frame size: {ref['frame_size']} bytes")
