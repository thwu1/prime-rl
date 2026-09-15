#!/usr/bin/env python3
"""Generate Undead puzzle instances with XOR-encrypted binary format + SQLite metadata."""
import random
import os
import sqlite3
import struct
import hashlib


def trace(grid, n, sr, sc, dr, dc):
    """Trace a sight line, counting visible monsters."""
    count = 0
    reflected = False
    r, c = sr, sc
    while 0 <= r < n and 0 <= c < n:
        cell = grid[r][c]
        if cell == '/':
            dr, dc = -dc, -dr
            reflected = True
        elif cell == '\\':
            dr, dc = dc, dr
            reflected = True
        elif cell == 'Z':
            count += 1
        elif cell == 'V' and not reflected:
            count += 1
        elif cell == 'G' and reflected:
            count += 1
        r += dr
        c += dc
    return count


def compute_clues(grid, n):
    t = [trace(grid, n, 0, c, 1, 0) for c in range(n)]
    b = [trace(grid, n, n - 1, c, -1, 0) for c in range(n)]
    l = [trace(grid, n, r, 0, 0, 1) for r in range(n)]
    ri = [trace(grid, n, r, n - 1, 0, -1) for r in range(n)]
    return t, b, l, ri


def generate(n, num_mirrors, base_seed):
    """Generate a puzzle with diverse clue distribution."""
    best = None
    best_score = -1

    for attempt in range(300):
        rng = random.Random(base_seed * 1000 + attempt)
        grid = [['.' for _ in range(n)] for _ in range(n)]

        positions = [(r, c) for r in range(n) for c in range(n)]
        rng.shuffle(positions)
        mirrors = {}
        for i in range(num_mirrors):
            r, c = positions[i]
            m = rng.choice(['/', '\\'])
            grid[r][c] = m
            mirrors[(r, c)] = m

        empty = [(r, c) for r in range(n) for c in range(n)
                 if grid[r][c] == '.']
        ne = len(empty)
        vc = ne // 3
        gc = ne // 3
        zc = ne - vc - gc

        monsters = ['V'] * vc + ['G'] * gc + ['Z'] * zc
        rng.shuffle(monsters)
        for i, (r, c) in enumerate(empty):
            grid[r][c] = monsters[i]

        t, b, l, ri = compute_clues(grid, n)
        all_c = t + b + l + ri
        diversity = len(set(all_c))
        nonzero = sum(1 for x in all_c if x > 0)
        score = diversity * 10 + nonzero

        if score > best_score:
            best_score = score
            best = (grid, mirrors, vc, gc, zc, t, b, l, ri)

    return best


def derive_key(seed_bytes, puzzle_id, length):
    """Derive per-puzzle XOR key using LCG seeded from header seed and puzzle_id.

    Key derivation:
      1. Initialize LCG state = puzzle_id * 0x9E3779B1 (Knuth multiplicative hash)
      2. For each byte position i:
         a. Advance LCG: state = state * 1103515245 + 12345 (mod 2^32)
         b. key[i] = seed[i % 16] XOR ((state >> 16) & 0xFF)
    """
    state = (puzzle_id * 2654435761) & 0xFFFFFFFF
    key = bytearray(length)
    for i in range(length):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        key[i] = seed_bytes[i % len(seed_bytes)] ^ ((state >> 16) & 0xFF)
    return bytes(key)


def xor_bytes(data, key):
    """XOR data with key (same length)."""
    return bytes(a ^ b for a, b in zip(data, key))


def write_binary(puzzles, seed_bytes, path):
    """Write puzzles to XOR-encrypted binary format.

    File layout (all integers little-endian):
      File header (28 bytes):
        magic       4 bytes   "UNDD"
        version     uint32    2
        count       uint32    number of puzzles
        seed        16 bytes  key derivation seed

      Per puzzle:
        id          uint32    (plaintext)
        block_len   uint32    (plaintext, byte length of encrypted block)
        encrypted   block_len bytes (XOR-encrypted with per-puzzle derived key)

      Decrypted block layout:
        dim         uint32
        nv          uint32    vampire count
        ng          uint32    ghost count
        nz          uint32    zombie count
        num_mirrors uint32
        mirrors     num_mirrors * 4 bytes each:
                      row   uint8
                      col   uint8
                      type  uint8  (0 = '/', 1 = '\\')
                      pad   uint8  (0)
        clues       dim * 4 uint32 values, interleaved:
                      for i in 0..dim-1: top[i] bot[i] left[i] right[i]
    """
    with open(path, 'wb') as f:
        f.write(b'UNDD')
        f.write(struct.pack('<II', 2, len(puzzles)))
        f.write(seed_bytes)

        for pid, (dim, nv, ng, nz, mirrors, top, bot, left, right) in puzzles:
            # Build plaintext block
            block = struct.pack('<IIIII', dim, nv, ng, nz, len(mirrors))

            for (r, c), m in sorted(mirrors.items()):
                mtype = 0 if m == '/' else 1
                block += struct.pack('<BBBB', r, c, mtype, 0)

            for i in range(dim):
                block += struct.pack('<IIII', top[i], bot[i], left[i], right[i])

            # Derive key and encrypt
            key = derive_key(seed_bytes, pid, len(block))
            enc_block = xor_bytes(block, key)

            # Write plaintext puzzle_id + block_len, then encrypted block
            f.write(struct.pack('<II', pid, len(enc_block)))
            f.write(enc_block)


def main():
    os.makedirs('/app/src', exist_ok=True)
    os.makedirs('/app/solutions', exist_ok=True)

    # Deterministic seed for reproducibility
    master_rng = random.Random(0xDEADBEEF)
    seed_bytes = bytes([master_rng.randint(0, 255) for _ in range(16)])

    configs = [
        (4, 4, 42),
        (5, 6, 137),
        (6, 9, 256),
        (7, 12, 389),
        (8, 16, 512),
        (9, 20, 673),
        (10, 25, 841),
    ]

    puzzles = []
    for i, (n, nm, seed) in enumerate(configs, 1):
        grid, mirrors, v, g, z, top, bot, left, right = generate(n, nm, seed)
        puzzles.append((i, (n, v, g, z, mirrors, top, bot, left, right)))
        print("Puzzle {}: {}x{}, {} mirrors, {}V {}G {}Z".format(
            i, n, n, nm, v, g, z))

    write_binary(puzzles, seed_bytes, '/app/puzzles.bin')

    # Write SQLite metadata
    conn = sqlite3.connect('/app/meta.db')
    cur = conn.cursor()

    cur.execute('''CREATE TABLE puzzle_meta (
        id INTEGER PRIMARY KEY,
        dim INTEGER NOT NULL,
        total_monsters INTEGER NOT NULL,
        clue_checksum TEXT NOT NULL
    )''')

    for pid, (dim, nv, ng, nz, mirrors, top, bot, left, right) in puzzles:
        all_clues = top + bot + left + right
        s = ','.join(str(c) for c in all_clues)
        checksum = hashlib.sha256(s.encode()).hexdigest()[:16]
        cur.execute('INSERT INTO puzzle_meta VALUES (?,?,?,?)',
                    (pid, dim, nv + ng + nz, checksum))

    conn.commit()
    conn.close()
    print("Wrote /app/puzzles.bin and /app/meta.db")
    print("Seed bytes: {}".format(seed_bytes.hex()))


if __name__ == '__main__':
    main()
