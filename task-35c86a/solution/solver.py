#!/usr/bin/env python3
"""
Wormhole NoC DRAM Reader Placement Optimizer.

Optimizes placement of 12 DRAM reader cores on available T-tiles in a
Tenstorrent Wormhole chip to minimize NoC congestion on data return paths.
"""

import json
import argparse
import sys
from collections import defaultdict


def load_config(path):
    with open(path) as f:
        return json.load(f)


def get_available_tiles(config, harvested_rows):
    tiles = set()
    for x in config['t_tile_columns']:
        for y in config['t_tile_rows']:
            if y not in harvested_rows:
                tiles.add((x, y))
    return tiles


def route_length(bx, by, rx, ry, noc_id, W, H):
    if noc_id == 0:
        return (rx - bx) % W + (ry - by) % H
    else:
        return (bx - rx) % W + (by - ry) % H


def compute_route(bx, by, rx, ry, noc_id, W, H):
    links = []
    cx, cy = bx, by
    if noc_id == 0:
        while cx != rx:
            nx = (cx + 1) % W
            links.append(((cx, cy), (nx, cy)))
            cx = nx
        while cy != ry:
            ny = (cy + 1) % H
            links.append(((cx, cy), (cx, ny)))
            cy = ny
    else:
        while cx != rx:
            nx = (cx - 1) % W
            links.append(((cx, cy), (nx, cy)))
            cx = nx
        while cy != ry:
            ny = (cy - 1) % H
            links.append(((cx, cy), (cx, ny)))
            cy = ny
    return links


def compute_all_routes(assignments, banks, W, H):
    routes = {}
    for bid, (rx, ry, noc) in assignments.items():
        bx, by = banks[bid]
        routes[bid] = compute_route(bx, by, rx, ry, noc, W, H)
    return routes


def compute_link_loads(routes, assignments):
    link_loads = defaultdict(int)
    for bid, route in routes.items():
        noc = assignments[bid][2]
        for link in route:
            link_loads[(noc, link)] += 1
    return link_loads


def congestion_metrics(link_loads):
    if not link_loads:
        return 1, 0, 0
    max_load = max(link_loads.values())
    total_excess = sum(v - 1 for v in link_loads.values() if v > 1)
    total_shared = sum(1 for v in link_loads.values() if v > 1)
    return max_load, total_excess, total_shared


def optimize(config, harvested_rows):
    W = config['grid_width']
    H = config['grid_height']
    banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}
    available = get_available_tiles(config, harvested_rows)

    if len(available) < 12:
        print(f"Error: only {len(available)} tiles available, need 12", file=sys.stderr)
        sys.exit(1)

    # Build sorted candidate list for each bank
    candidates = {}
    for bid, (bx, by) in banks.items():
        cands = []
        for (rx, ry) in available:
            for noc in [0, 1]:
                length = route_length(bx, by, rx, ry, noc, W, H)
                cands.append((length, rx, ry, noc))
        cands.sort()
        candidates[bid] = cands

    # Phase 1: Greedy assignment — most constrained banks first
    bank_order = sorted(banks.keys(),
                        key=lambda bid: (candidates[bid][0][0], -bid),
                        reverse=True)

    used_tiles = set()
    assignments = {}

    for bid in bank_order:
        for length, rx, ry, noc in candidates[bid]:
            if (rx, ry) not in used_tiles:
                assignments[bid] = (rx, ry, noc)
                used_tiles.add((rx, ry))
                break

    # Phase 2: Iterative congestion reduction
    routes = compute_all_routes(assignments, banks, W, H)
    link_loads = compute_link_loads(routes, assignments)
    max_load, total_excess, total_shared = congestion_metrics(link_loads)

    for iteration in range(100):
        if max_load <= 1:
            break
        improved = False

        for bid in banks:
            if max_load <= 1:
                break

            bx, by = banks[bid]
            cur_rx, cur_ry, cur_noc = assignments[bid]
            cur_route = routes[bid]

            # Remove this bank's contribution
            for link in cur_route:
                key = (cur_noc, link)
                link_loads[key] -= 1
                if link_loads[key] == 0:
                    del link_loads[key]

            best_score = None
            best_alt = None
            best_route = None

            for length, rx, ry, noc in candidates[bid][:80]:
                if (rx, ry) in used_tiles and (rx, ry) != (cur_rx, cur_ry):
                    continue

                test_route = compute_route(bx, by, rx, ry, noc, W, H)

                # Temporarily add
                for link in test_route:
                    link_loads[(noc, link)] += 1

                test_max, test_excess, _ = congestion_metrics(link_loads)
                score = (test_max, test_excess, length)

                if best_score is None or score < best_score:
                    best_score = score
                    best_alt = (rx, ry, noc)
                    best_route = list(test_route)

                # Remove temporary
                for link in test_route:
                    link_loads[(noc, link)] -= 1
                    if link_loads[(noc, link)] == 0:
                        del link_loads[(noc, link)]

            # Apply best
            if best_alt:
                rx, ry, noc = best_alt
                for link in best_route:
                    link_loads[(noc, link)] += 1

                if best_alt != (cur_rx, cur_ry, cur_noc):
                    used_tiles.discard((cur_rx, cur_ry))
                    used_tiles.add((rx, ry))
                    assignments[bid] = best_alt
                    routes[bid] = best_route
                    new_max, new_excess, _ = congestion_metrics(link_loads)
                    if new_max < max_load or (new_max == max_load and new_excess < total_excess):
                        improved = True
                    max_load, total_excess = new_max, new_excess
                else:
                    # Re-add original
                    for link in best_route:
                        link_loads[(noc, link)] += 1

        if not improved:
            break

    # Recompute final metrics cleanly
    routes = compute_all_routes(assignments, banks, W, H)
    link_loads = compute_link_loads(routes, assignments)
    max_load, total_excess, total_shared = congestion_metrics(link_loads)

    # VC assignment
    row_noc_groups = defaultdict(list)
    for bid, (rx, ry, noc) in assignments.items():
        row_noc_groups[(ry, noc)].append(bid)

    vc_map = {}
    for key, bids in row_noc_groups.items():
        for i, bid in enumerate(sorted(bids)):
            vc_map[bid] = i % 2

    # Bandwidth calculation
    per_bank_bw = config['per_bank_bandwidth_gbps']
    noc_link_bw = config['noc_link_bandwidth_gbps']

    total_eff = 0.0
    for bid in banks:
        noc = assignments[bid][2]
        route = routes[bid]
        if not route:
            path_max = 1
        else:
            path_max = max(link_loads[(noc, link)] for link in route)
        eff = min(per_bank_bw, noc_link_bw / path_max)
        total_eff += eff

    bandwidth_pct = total_eff / (12 * per_bank_bw) * 100

    # Build output
    output = {
        "placements": [],
        "routes": [],
        "congestion": {
            "total_shared_links": total_shared,
            "max_link_load": max_load,
            "total_excess_load": total_excess
        },
        "estimated_bandwidth_pct": round(bandwidth_pct, 2)
    }

    for bid in sorted(banks.keys()):
        rx, ry, noc = assignments[bid]
        output["placements"].append({
            "bank_id": bid,
            "reader_x": rx,
            "reader_y": ry,
            "noc_id": noc,
            "vc": vc_map[bid]
        })
        output["routes"].append({
            "bank_id": bid,
            "links": [[[l[0][0], l[0][1]], [l[1][0], l[1][1]]] for l in routes[bid]]
        })

    return output


def main():
    parser = argparse.ArgumentParser(description='Wormhole NoC DRAM Reader Placement Optimizer')
    parser.add_argument('--config', required=True, help='Path to wormhole grid config JSON')
    parser.add_argument('--harvested-rows', default='', help='Comma-separated harvested row indices')
    parser.add_argument('--output', required=True, help='Output JSON path')
    args = parser.parse_args()

    config = load_config(args.config)

    hr_str = args.harvested_rows.strip()
    if hr_str:
        harvested = set(int(r.strip()) for r in hr_str.split(',') if r.strip())
    else:
        harvested = set()

    result = optimize(config, harvested)

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
