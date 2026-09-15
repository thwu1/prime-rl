#!/usr/bin/env python3
"""
Wormhole NoC Simulation & Firmware Generation Pipeline.

Fixes bugs in the C NoC link congestion simulator, computes optimal DRAM
reader placements on the 10x12 toroidal grid, validates via the compiled
simulator, and generates cross-assembled RISC-V RV32I firmware for NoC
Route Configuration Table entries.
"""

import json
import argparse
import os
import subprocess
import sys
import tempfile
from collections import defaultdict


def load_config(path):
    with open(path) as f:
        return json.load(f)


def fix_and_compile_simulator():
    """Identify and fix bugs in noc_sim.c, then compile with make."""
    sim_src = '/app/noc_sim.c'
    sim_bin = '/app/noc_sim'
    fixes_file = '/app/.noc_sim_fixes.json'

    # Return cached result if already done
    if os.path.exists(sim_bin) and os.path.exists(fixes_file):
        with open(fixes_file) as f:
            return True, json.load(f)

    with open(sim_src) as f:
        code = f.read()

    bugs_fixed = []

    # Bug 1: NoC 1 horizontal routing goes east (+1) instead of west (-1).
    # The comment says "horizontal then vertical" without specifying direction,
    # and the code uses (cx + 1) which is the same as NoC 0 (east).
    # Per the Wormhole architecture, NoC 1 routes west then north.
    old_noc1_route = (
        '        /* NoC 1: horizontal then vertical */\n'
        '        while (cx != rx) {\n'
        '            int nx = (cx + 1) % GRID_W;'
    )
    new_noc1_route = (
        '        /* NoC 1: west then north */\n'
        '        while (cx != rx) {\n'
        '            int nx = (cx - 1 + GRID_W) % GRID_W;'
    )
    if old_noc1_route in code:
        code = code.replace(old_noc1_route, new_noc1_route)
        bugs_fixed.append("NoC 1 horizontal routing corrected from east to west")

    # Bug 2: LinkKey struct does not include noc_id. The find_or_create_link
    # function accepts a 'noc' parameter but the key comparison ignores it,
    # causing link loads from both NoC fabrics to be merged. Since the two
    # NoC fabrics have physically independent links, their loads should be
    # tracked separately.
    old_struct = (
        'typedef struct {\n'
        '    int from_x, from_y;\n'
        '    int to_x, to_y;\n'
        '} LinkKey;'
    )
    new_struct = (
        'typedef struct {\n'
        '    int noc_id;\n'
        '    int from_x, from_y;\n'
        '    int to_x, to_y;\n'
        '} LinkKey;'
    )
    if old_struct in code:
        code = code.replace(old_struct, new_struct)
        bugs_fixed.append("LinkKey now includes noc_id for per-fabric load tracking")

    # Fix the comparison in find_or_create_link to check noc_id
    old_cmp = (
        '        if (link_table[i].key.from_x == fx &&\n'
        '            link_table[i].key.from_y == fy &&\n'
        '            link_table[i].key.to_x == tx &&\n'
        '            link_table[i].key.to_y == ty) {'
    )
    new_cmp = (
        '        if (link_table[i].key.noc_id == noc &&\n'
        '            link_table[i].key.from_x == fx &&\n'
        '            link_table[i].key.from_y == fy &&\n'
        '            link_table[i].key.to_x == tx &&\n'
        '            link_table[i].key.to_y == ty) {'
    )
    if old_cmp in code:
        code = code.replace(old_cmp, new_cmp)

    # Fix the initialization to include noc_id
    # Guard: only apply if noc_id assignment isn't already in the function
    if 'link_table[link_count].key.noc_id = noc;' not in code:
        old_init = '    link_table[link_count].key.from_x = fx;'
        new_init = (
            '    link_table[link_count].key.noc_id = noc;\n'
            '    link_table[link_count].key.from_x = fx;'
        )
        code = code.replace(old_init, new_init, 1)

    with open(sim_src, 'w') as f:
        f.write(code)

    # Compile
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, text=True)
    result = subprocess.run(['make', '-C', '/app'],
                            capture_output=True, text=True)
    compiled = result.returncode == 0

    if not compiled:
        print(f"Compilation failed: {result.stderr}", file=sys.stderr)

    # If bugs_fixed is empty (already patched), try to load saved fixes
    if not bugs_fixed and os.path.exists(fixes_file):
        with open(fixes_file) as f:
            bugs_fixed = json.load(f)
    elif bugs_fixed:
        with open(fixes_file, 'w') as f:
            json.dump(bugs_fixed, f)

    return compiled, bugs_fixed


def run_c_simulator(placements_list, banks):
    """Run the compiled C simulator to validate a placement configuration."""
    csv_path = tempfile.mktemp(suffix='.csv')
    with open(csv_path, 'w') as f:
        f.write("bank_id,bank_x,bank_y,reader_x,reader_y,noc_id\n")
        for p in placements_list:
            bx, by = banks[p['bank_id']]
            f.write(f"{p['bank_id']},{bx},{by},"
                    f"{p['reader_x']},{p['reader_y']},{p['noc_id']}\n")

    try:
        result = subprocess.run(['/app/noc_sim', csv_path],
                                capture_output=True, text=True, timeout=30)
        os.unlink(csv_path)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        if os.path.exists(csv_path):
            os.unlink(csv_path)
        return None


# ---- Grid helpers ----

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
            nx = (cx - 1 + W) % W
            links.append(((cx, cy), (nx, cy)))
            cx = nx
        while cy != ry:
            ny = (cy - 1 + H) % H
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


# ---- Optimizer ----

def optimize(config, harvested_rows):
    """Compute optimal DRAM reader placements using greedy + iterative."""
    W = config['grid_width']
    H = config['grid_height']
    banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}
    available = get_available_tiles(config, harvested_rows)

    if len(available) < 12:
        print(f"Error: only {len(available)} tiles available, need 12",
              file=sys.stderr)
        sys.exit(1)

    # Build sorted candidate list for each bank (shortest path first)
    candidates = {}
    for bid, (bx, by) in banks.items():
        cands = []
        for (rx, ry) in available:
            for noc in [0, 1]:
                length = route_length(bx, by, rx, ry, noc, W, H)
                cands.append((length, rx, ry, noc))
        cands.sort()
        candidates[bid] = cands

    # Phase 1: Greedy — most constrained banks first
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

            # Remove current bank's contribution to link loads
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

            # Apply best candidate
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
                    if (new_max < max_load or
                            (new_max == max_load and new_excess < total_excess)):
                        improved = True
                    max_load, total_excess = new_max, new_excess
                else:
                    # Re-add original (best was same as current)
                    for link in best_route:
                        link_loads[(noc, link)] += 1

        if not improved:
            break

    # Recompute final metrics cleanly
    routes = compute_all_routes(assignments, banks, W, H)
    link_loads = compute_link_loads(routes, assignments)
    max_load, total_excess, total_shared = congestion_metrics(link_loads)

    # VC assignment: same-row, same-noc readers get different VCs
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

    return (assignments, routes, vc_map,
            max_load, total_excess, total_shared, bandwidth_pct)


# ---- Firmware generation ----

def generate_firmware(assignments, vc_map, banks):
    """Generate RISC-V assembly for RCT entries, cross-assemble, verify."""
    fw_dir = '/app/firmware'
    os.makedirs(fw_dir, exist_ok=True)

    # Load RCT register spec
    with open('/app/tlb_spec.json') as f:
        spec = json.load(f)

    base_addr = int(spec['noc_route_config']['base_addr'], 16)
    base_hi = (base_addr >> 12) & 0xFFFFF

    firmware = []

    for bid in sorted(assignments.keys()):
        rx, ry, noc_sel = assignments[bid]
        vc = vc_map[bid]
        bx, by = banks[bid]

        # Encode RCT value per the spec:
        # low32 = (enable<<31) | (vc<<13) | (noc_sel<<12) | (target_y<<6) | target_x
        # high32 = dram_addr_offset (0 for base access)
        low32 = (1 << 31) | (vc << 13) | (noc_sel << 12) | (by << 6) | bx
        high32 = 0
        rct_value = (high32 << 32) | low32

        # Generate RISC-V RV32I assembly
        asm_file = f'{fw_dir}/bank_{bid}.s'
        asm_code = (
            f'.section .text\n'
            f'.globl configure_rct_bank{bid}\n'
            f'configure_rct_bank{bid}:\n'
            f'    lui a0, 0x{base_hi:x}\n'
            f'    li a1, 0x{low32:x}\n'
            f'    sw a1, 0(a0)\n'
            f'    li a2, 0\n'
            f'    sw a2, 4(a0)\n'
            f'    ret\n'
        )
        with open(asm_file, 'w') as f:
            f.write(asm_code)

        # Cross-assemble for RV32I
        obj_file = asm_file.replace('.s', '.o')
        asm_result = subprocess.run(
            ['riscv64-linux-gnu-as', '-march=rv32i', '-mabi=ilp32',
             '-o', obj_file, asm_file],
            capture_output=True, text=True
        )

        # Verify with objdump
        obj_verified = False
        if asm_result.returncode == 0 and os.path.exists(obj_file):
            dump = subprocess.run(
                ['riscv64-linux-gnu-objdump', '-d', obj_file],
                capture_output=True, text=True
            )
            if (dump.returncode == 0 and
                    'sw' in dump.stdout and 'lui' in dump.stdout):
                obj_verified = True

        firmware.append({
            'bank_id': bid,
            'rct_value_hex': f'{rct_value:016x}',
            'asm_file': asm_file,
            'obj_verified': obj_verified
        })

    return firmware


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description='Wormhole NoC Simulation & Firmware Pipeline')
    parser.add_argument('--config', required=True,
                        help='Path to wormhole grid config JSON')
    parser.add_argument('--harvested-rows', default='',
                        help='Comma-separated harvested row indices')
    parser.add_argument('--output', required=True,
                        help='Output JSON path')
    args = parser.parse_args()

    config = load_config(args.config)

    hr_str = args.harvested_rows.strip()
    if hr_str:
        harvested = set(int(r.strip()) for r in hr_str.split(',') if r.strip())
    else:
        harvested = set()

    # 1. Fix and compile the C simulator
    compiled, bugs_fixed = fix_and_compile_simulator()

    # 2. Compute optimal reader placements
    banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}
    (assignments, routes, vc_map,
     max_load, total_excess, total_shared,
     bandwidth_pct) = optimize(config, harvested)

    # Build placements list
    placements_list = []
    for bid in sorted(assignments.keys()):
        rx, ry, noc = assignments[bid]
        placements_list.append({
            'bank_id': bid,
            'reader_x': rx,
            'reader_y': ry,
            'noc_id': noc,
            'vc': vc_map[bid]
        })

    # 3. Validate with compiled C simulator
    sim_result = run_c_simulator(placements_list, banks)
    sim_validation = {
        'compiled': compiled,
        'bugs_fixed': bugs_fixed,
        'sim_max_link_load': sim_result['max_link_load'] if sim_result else -1,
        'validation_passed': (sim_result is not None and
                              sim_result['max_link_load'] == max_load)
    }

    # 4. Generate RISC-V firmware
    firmware = generate_firmware(assignments, vc_map, banks)

    # 5. Assemble output
    output = {
        'placements': placements_list,
        'routes': [],
        'congestion': {
            'total_shared_links': total_shared,
            'max_link_load': max_load,
            'total_excess_load': total_excess
        },
        'estimated_bandwidth_pct': round(bandwidth_pct, 2),
        'simulator_validation': sim_validation,
        'firmware': firmware
    }

    for bid in sorted(assignments.keys()):
        output['routes'].append({
            'bank_id': bid,
            'links': [[[l[0][0], l[0][1]], [l[1][0], l[1][1]]]
                      for l in routes[bid]]
        })

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)


if __name__ == '__main__':
    main()
