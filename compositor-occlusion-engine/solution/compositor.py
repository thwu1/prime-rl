#!/usr/bin/env python3

"""
Compositor script — reads scenario from stdin, writes frame data to stdout.
"""

import sys
from engine import compute_visible_regions, compute_dirty_regions


def main():
    screen_w = screen_h = 0
    windows = {}
    frame_num = 0
    prev_regions = {}

    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue

        cmd = parts[0]

        if cmd == "SCREEN":
            screen_w, screen_h = int(parts[1]), int(parts[2])
        elif cmd == "CREATE":
            wid = int(parts[1])
            x, y, w, h, z = (
                int(parts[2]), int(parts[3]), int(parts[4]),
                int(parts[5]), int(parts[6]),
            )
            windows[wid] = (x, y, w, h, z)
        elif cmd == "DESTROY":
            wid = int(parts[1])
            windows.pop(wid, None)
        elif cmd == "MOVE":
            wid = int(parts[1])
            x, y = int(parts[2]), int(parts[3])
            if wid in windows:
                _, _, w, h, z = windows[wid]
                windows[wid] = (x, y, w, h, z)
        elif cmd == "RESIZE":
            wid = int(parts[1])
            w, h = int(parts[2]), int(parts[3])
            if wid in windows:
                x, y, _, _, z = windows[wid]
                windows[wid] = (x, y, w, h, z)
        elif cmd == "REORDER":
            wid = int(parts[1])
            z = int(parts[2])
            if wid in windows:
                x, y, w, h, _ = windows[wid]
                windows[wid] = (x, y, w, h, z)
        elif cmd == "FRAME":
            frame_num += 1
            win_list = [(wid, *vals) for wid, vals in windows.items()]
            regions = compute_visible_regions(screen_w, screen_h, win_list)
            dirty = compute_dirty_regions(prev_regions, regions, screen_w, screen_h)

            def region_sort_key(owner):
                return (-1,) if owner == "bg" else (owner,)

            print(f"FRAME {frame_num}")

            region_count = 0
            for owner in sorted(regions.keys(), key=region_sort_key):
                rects = sorted(regions[owner], key=lambda r: (r[1], r[0]))
                for r in rects:
                    print(f"REGION {owner} {r[0]} {r[1]} {r[2]} {r[3]}")
                    region_count += 1

            dirty_sorted = sorted(dirty, key=lambda r: (r[1], r[0]))
            for r in dirty_sorted:
                print(f"DIRTY {r[0]} {r[1]} {r[2]} {r[3]}")

            total_pixels = sum(
                r[2] * r[3] for rects in regions.values() for r in rects
            )
            dirty_pixels = sum(r[2] * r[3] for r in dirty)
            print(f"STATS {total_pixels} {dirty_pixels} {region_count}")
            print("END_FRAME")

            prev_regions = regions


if __name__ == "__main__":
    main()
