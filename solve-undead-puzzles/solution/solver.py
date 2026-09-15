#!/usr/bin/env python3
"""
Undead puzzle solver — decrypts XOR-encrypted binary data, solves via
backtracking with constraint propagation, writes solutions in validator format.
"""

import os
import sys
import struct

BIN_PATH = '/app/puzzles.bin'
SEED_LEN = 16


def derive_key(seed_bytes, puzzle_id, length):
    """Derive per-puzzle XOR key using LCG mixed with header seed.

    Key derivation:
      1. state = puzzle_id * 0x9E3779B1 (Knuth multiplicative hash, mod 2^32)
      2. For each byte i:
         a. state = state * 1103515245 + 12345 (mod 2^32, glibc LCG)
         b. key[i] = seed[i % 16] XOR ((state >> 16) & 0xFF)
    """
    state = (puzzle_id * 2654435761) & 0xFFFFFFFF
    key = bytearray(length)
    for i in range(length):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        key[i] = seed_bytes[i % SEED_LEN] ^ ((state >> 16) & 0xFF)
    return bytes(key)


def xor_decrypt(data, key):
    """XOR data with key of equal length."""
    return bytes(a ^ b for a, b in zip(data, key))


def parse_binary(path):
    """Parse the XOR-encrypted binary puzzle format.

    File layout:
      Header (28 bytes):
        magic[4]    = "UNDD"
        version     = uint32 LE (2)
        count       = uint32 LE
        seed[16]    = key derivation seed

      Per puzzle:
        id          = uint32 LE (plaintext)
        block_len   = uint32 LE (plaintext)
        encrypted   = block_len bytes (XOR with derived key)

      Decrypted block:
        dim, nv, ng, nz, num_mirrors = 5 x uint32 LE
        mirrors = num_mirrors * (row u8, col u8, type u8, pad u8)
        clues = dim * (top u32, bot u32, left u32, right u32)
    """
    puzzles = {}
    with open(path, 'rb') as f:
        magic = f.read(4)
        if magic != b'UNDD':
            print("Bad magic: {}".format(magic), file=sys.stderr)
            return puzzles
        version, count = struct.unpack('<II', f.read(8))
        if version != 2:
            print("Unexpected version: {}".format(version), file=sys.stderr)
            return puzzles
        seed = f.read(SEED_LEN)

        for _ in range(count):
            pid, blen = struct.unpack('<II', f.read(8))
            enc_block = f.read(blen)

            # Decrypt
            key = derive_key(seed, pid, blen)
            block = xor_decrypt(enc_block, key)

            # Parse decrypted block
            dim, nv, ng, nz, nm = struct.unpack_from('<IIIII', block, 0)
            offset = 20

            mirrors = {}
            for _ in range(nm):
                row, col, mtype, pad = struct.unpack_from('<BBBB', block, offset)
                mirrors[(row, col)] = '/' if mtype == 0 else '\\'
                offset += 4

            top, bot, left, right = [], [], [], []
            for i in range(dim):
                t, b, l, r = struct.unpack_from('<IIII', block, offset)
                top.append(t)
                bot.append(b)
                left.append(l)
                right.append(r)
                offset += 16

            puzzles[pid] = (dim, nv, ng, nz, mirrors, top, bot, left, right)

    return puzzles


def precompute_line(n, mirrors, sr, sc, dr, dc):
    """Precompute the path of a sight line through the grid,
    recording which non-mirror cells it visits and whether
    the line has been reflected at each visit."""
    path = []
    reflected = False
    r, c = sr, sc
    while 0 <= r < n and 0 <= c < n:
        if (r, c) in mirrors:
            m = mirrors[(r, c)]
            if m == '/':
                dr, dc = -dc, -dr
            else:
                dr, dc = dc, dr
            reflected = True
        else:
            path.append((r, c, reflected))
        r += dr
        c += dc
    return path


def solve(n, v_total, g_total, z_total, mirrors, top, bottom, left, right):
    """Solve an Undead puzzle via backtracking with constraint propagation."""
    empty = [(r, c) for r in range(n) for c in range(n)
             if (r, c) not in mirrors]
    num_cells = len(empty)
    cell_idx = {rc: i for i, rc in enumerate(empty)}

    # Precompute all 4N sight lines
    all_lines = []
    for c in range(n):
        all_lines.append(
            (precompute_line(n, mirrors, 0, c, 1, 0), top[c]))
    for c in range(n):
        all_lines.append(
            (precompute_line(n, mirrors, n - 1, c, -1, 0), bottom[c]))
    for r in range(n):
        all_lines.append(
            (precompute_line(n, mirrors, r, 0, 0, 1), left[r]))
    for r in range(n):
        all_lines.append(
            (precompute_line(n, mirrors, r, n - 1, 0, -1), right[r]))

    num_lines = len(all_lines)

    # For each cell, record which lines visit it and the contribution
    # of each monster type (V=0, G=1, Z=2) to each line's count
    cell_visits_raw = [dict() for _ in range(num_cells)]
    for li, (path, _) in enumerate(all_lines):
        for r, c, ref in path:
            ci = cell_idx.get((r, c))
            if ci is not None:
                if li not in cell_visits_raw[ci]:
                    cell_visits_raw[ci][li] = []
                cell_visits_raw[ci][li].append(ref)

    cell_line_info = [[] for _ in range(num_cells)]
    for ci in range(num_cells):
        for li, refs in cell_visits_raw[ci].items():
            visits = len(refs)
            cv = sum(1 for ref in refs if not ref)   # V contribution
            cg = sum(1 for ref in refs if ref)       # G contribution
            cz = visits                              # Z contribution
            cell_line_info[ci].append((li, visits, cv, cg, cz))

    assignment = [None] * num_cells
    remaining = [v_total, g_total, z_total]
    line_counts = [0] * num_lines
    line_unknowns = [len(path) for path, _ in all_lines]
    assigned_set = [False] * num_cells
    domains = [set([0, 1, 2]) for _ in range(num_cells)]

    def get_contrib(ci, t):
        result = []
        for li, visits, cv, cg, cz in cell_line_info[ci]:
            contrib = (cv, cg, cz)[t]
            result.append((li, contrib, visits))
        return result

    def is_type_feasible(ci, t):
        if remaining[t] <= 0:
            return False
        for li, visits, cv, cg, cz in cell_line_info[ci]:
            contrib = (cv, cg, cz)[t]
            new_count = line_counts[li] + contrib
            new_unk = line_unknowns[li] - visits
            _, expected = all_lines[li]
            if new_count > expected:
                return False
            if new_unk >= 0 and new_count + new_unk < expected:
                return False
        return True

    def propagate():
        forced = []
        changed = True
        while changed:
            changed = False
            for ci in range(num_cells):
                if assigned_set[ci]:
                    continue
                feasible = []
                for t in list(domains[ci]):
                    if is_type_feasible(ci, t):
                        feasible.append(t)
                    else:
                        domains[ci].discard(t)
                        changed = True
                if len(feasible) == 0:
                    return False, forced
                if len(feasible) == 1:
                    t = feasible[0]
                    assignment[ci] = t
                    assigned_set[ci] = True
                    remaining[t] -= 1
                    for li, contrib, visits in get_contrib(ci, t):
                        line_counts[li] += contrib
                        line_unknowns[li] -= visits
                    forced.append((ci, t))
                    changed = True
            for t in range(3):
                if remaining[t] < 0:
                    return False, forced
            for li in range(num_lines):
                _, expected = all_lines[li]
                if line_counts[li] > expected:
                    return False, forced
                if line_unknowns[li] == 0 and line_counts[li] != expected:
                    return False, forced
        return True, forced

    def undo_forced(forced):
        for ci, t in reversed(forced):
            for li, contrib, visits in get_contrib(ci, t):
                line_counts[li] -= contrib
                line_unknowns[li] += visits
            remaining[t] += 1
            assigned_set[ci] = False
            assignment[ci] = None

    solution = [None]

    def backtrack():
        if solution[0] is not None:
            return
        ok, forced = propagate()
        if not ok:
            undo_forced(forced)
            return
        unassigned = [ci for ci in range(num_cells) if not assigned_set[ci]]
        if not unassigned:
            for li in range(num_lines):
                if line_counts[li] != all_lines[li][1]:
                    undo_forced(forced)
                    return
            solution[0] = assignment[:]
            undo_forced(forced)
            return
        best_ci = min(unassigned, key=lambda ci: len(domains[ci]))
        best_domain = sorted(domains[best_ci])
        for t in best_domain:
            if remaining[t] <= 0:
                continue
            if not is_type_feasible(best_ci, t):
                continue
            saved_domains = [d.copy() for d in domains]
            assignment[best_ci] = t
            assigned_set[best_ci] = True
            remaining[t] -= 1
            deltas = get_contrib(best_ci, t)
            for li, contrib, visits in deltas:
                line_counts[li] += contrib
                line_unknowns[li] -= visits
            domains[best_ci] = {t}
            backtrack()
            if solution[0] is not None:
                undo_forced(forced)
                return
            for li, contrib, visits in deltas:
                line_counts[li] -= contrib
                line_unknowns[li] += visits
            remaining[t] += 1
            assigned_set[best_ci] = False
            assignment[best_ci] = None
            for ci2 in range(num_cells):
                domains[ci2] = saved_domains[ci2]
        undo_forced(forced)

    backtrack()

    if solution[0] is None:
        return None

    types = ['V', 'G', 'Z']
    grid = [[None] * n for _ in range(n)]
    for (r, c), m in mirrors.items():
        grid[r][c] = m
    for i, (r, c) in enumerate(empty):
        grid[r][c] = types[solution[0][i]]
    return grid


def main():
    os.makedirs('/app/solutions', exist_ok=True)

    puzzles = parse_binary(BIN_PATH)
    if not puzzles:
        print("Failed to parse puzzle data", file=sys.stderr)
        sys.exit(1)

    for i in range(1, 8):
        if i not in puzzles:
            print("Puzzle {} not found".format(i), file=sys.stderr)
            continue

        n, v, g, z, mirrors, top, bottom, left, right = puzzles[i]
        print("Solving puzzle {} ({}x{})...".format(i, n, n), flush=True)
        grid = solve(n, v, g, z, mirrors, top, bottom, left, right)

        if grid is None:
            print("  No solution found!", file=sys.stderr, flush=True)
            continue

        sf = '/app/solutions/solution_{}.txt'.format(i)
        with open(sf, 'w') as f:
            f.write('UNDEAD v1 {}\n'.format(i))
            for row in grid:
                f.write(''.join(row) + '\n')
        print("  Solved -> {}".format(sf), flush=True)


if __name__ == '__main__':
    main()
