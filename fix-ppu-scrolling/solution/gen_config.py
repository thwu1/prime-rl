#!/usr/bin/env python3
"""
Generate render_config.txt for the C renderer by simulating the
corrected PPU state machine on register_trace.json to extract
per-region 9-bit scroll coordinates.

The C renderer uses a stateless per-region approach: it takes direct
scroll coordinates and renders each region independently. This script
bridges the gap by running the stateful PPU register write trace
through the corrected state machine and extracting the effective
scroll position at each region boundary.
"""


import json
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


def v_to_scroll(ppu):
    """Extract 9-bit scroll coordinates from current v and x registers.

    scroll_x = nt_h * 256 + coarseX * 8 + fineX
    scroll_y = nt_v * 256 + coarseY * 8 + fineY
    """
    fine_y = (ppu.v >> 12) & 7
    nt_v = (ppu.v >> 11) & 1
    nt_h = (ppu.v >> 10) & 1
    coarse_y = (ppu.v >> 5) & 0x1F
    coarse_x = ppu.v & 0x1F

    scroll_x = (nt_h << 8) | (coarse_x << 3) | ppu.x
    scroll_y = (nt_v << 8) | (coarse_y << 3) | fine_y
    return scroll_x, scroll_y


def main():
    with open('/app/register_trace.json') as f:
        trace = json.load(f)

    ppu = PPUScrollState()
    mirroring = trace['mirroring']
    pat_base = trace['pattern_table'] * 0x1000

    # Process initial register writes (VBlank setup)
    for op in trace['initial_ops']:
        process_op(ppu, op)

    # Pre-render: copy vertical scroll bits from t to v
    ppu.copy_vertical()

    # Identify region boundaries from scanline_ops keys
    boundaries = set(int(k) for k in trace['scanline_ops'].keys())
    sorted_boundaries = sorted(boundaries)

    regions = []

    for scanline in range(240):
        # Apply mid-frame register writes for this scanline
        key = str(scanline)
        if key in trace['scanline_ops']:
            for op in trace['scanline_ops'][key]:
                process_op(ppu, op)

        # Copy horizontal scroll bits from t to v (dot 257)
        ppu.copy_horizontal()

        # Record scroll position at region boundaries
        if scanline == 0 or scanline in boundaries:
            sx, sy = v_to_scroll(ppu)
            future = [b for b in sorted_boundaries if b > scanline]
            end_sl = future[0] - 1 if future else 239
            regions.append((scanline, end_sl, sx, sy))

        # Increment Y (rendering calls increment_coarse_x per tile,
        # but copy_horizontal restores X each scanline, so only Y
        # state propagates between scanlines)
        ppu.increment_y()

    # Write render_config.txt in the format expected by the C renderer
    with open('/app/render_config.txt', 'w') as f:
        f.write(f"{mirroring}\n")
        f.write(f"{pat_base}\n")
        f.write(f"{len(regions)}\n")
        for start, end, sx, sy in regions:
            f.write(f"{start} {end} {sx} {sy}\n")

    print(f"Generated render_config.txt with {len(regions)} regions")


if __name__ == '__main__':
    main()
