"""Verification tests for Undead puzzle solutions from XOR-encrypted binary data."""
import os
import struct
import subprocess
import hashlib
import sqlite3
import pytest


BIN_PATH = '/app/puzzles.bin'
META_DB = '/app/meta.db'
SOL_DIR = '/app/solutions'
VALIDATOR = '/app/undead-check'
SEED_LEN = 16


def derive_key(seed_bytes, puzzle_id, length):
    """Derive per-puzzle XOR key using LCG mixed with header seed."""
    state = (puzzle_id * 2654435761) & 0xFFFFFFFF
    key = bytearray(length)
    for i in range(length):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        key[i] = seed_bytes[i % SEED_LEN] ^ ((state >> 16) & 0xFF)
    return bytes(key)


def xor_decrypt(data, key):
    """XOR data with key of same length."""
    return bytes(a ^ b for a, b in zip(data, key))


def parse_binary_puzzles(path):
    """Parse the XOR-encrypted binary puzzle format."""
    puzzles = {}
    with open(path, 'rb') as f:
        magic = f.read(4)
        assert magic == b'UNDD', "Bad magic: {}".format(magic)
        version, count = struct.unpack('<II', f.read(8))
        assert version == 2, "Expected version 2, got {}".format(version)
        seed = f.read(SEED_LEN)

        for _ in range(count):
            pid, blen = struct.unpack('<II', f.read(8))
            enc_block = f.read(blen)

            key = derive_key(seed, pid, blen)
            block = xor_decrypt(enc_block, key)

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


def trace_line(grid, n, sr, sc, dr, dc):
    """Trace a sight line through a solved grid, counting visible monsters."""
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


@pytest.mark.parametrize("puzzle_id", [1, 2, 3, 4, 5, 6, 7])
def test_solution_file_exists(puzzle_id):
    """Verify solution file exists."""
    sol_path = os.path.join(SOL_DIR, 'solution_{}.txt'.format(puzzle_id))
    assert os.path.exists(sol_path), \
        "Solution file missing: {}".format(sol_path)


@pytest.mark.parametrize("puzzle_id", [1, 2, 3, 4, 5, 6, 7])
def test_solution_schema(puzzle_id):
    """Verify solution file conforms to the documented schema."""
    sol_path = os.path.join(SOL_DIR, 'solution_{}.txt'.format(puzzle_id))
    assert os.path.exists(sol_path), "Solution file missing"

    with open(sol_path) as f:
        content = f.read()

    # Must end with exactly one newline
    assert content.endswith('\n'), "File must end with newline"
    assert not content.endswith('\n\n'), "No blank lines after grid"

    lines = content.rstrip('\n').split('\n')

    # Header line check
    header = lines[0]
    expected_header = 'UNDEAD v1 {}'.format(puzzle_id)
    assert header == expected_header, \
        "Header mismatch: expected '{}', got '{}'".format(expected_header, header)

    # Get dimension from SQLite
    conn = sqlite3.connect(META_DB)
    cur = conn.cursor()
    cur.execute('SELECT dim FROM puzzle_meta WHERE id = ?', (puzzle_id,))
    row = cur.fetchone()
    conn.close()
    assert row is not None, "Puzzle {} not in metadata".format(puzzle_id)
    dim = row[0]

    # Grid dimensions
    grid_lines = lines[1:]
    assert len(grid_lines) == dim, \
        "Expected {} grid rows, got {}".format(dim, len(grid_lines))

    valid_chars = set('VGZ/\\')
    for r, line in enumerate(grid_lines):
        assert len(line) == dim, \
            "Row {}: expected {} chars, got {}".format(r, dim, len(line))
        for c, ch in enumerate(line):
            assert ch in valid_chars, \
                "Row {} col {}: invalid char '{}'".format(r, c, ch)
        # No trailing whitespace
        assert line == line.rstrip(), \
            "Row {}: trailing whitespace detected".format(r)


@pytest.mark.parametrize("puzzle_id", [1, 2, 3, 4, 5, 6, 7])
def test_solution_content(puzzle_id):
    """Verify solution grid satisfies all Undead puzzle constraints."""
    puzzles = parse_binary_puzzles(BIN_PATH)
    assert puzzle_id in puzzles, "Puzzle {} not in data file".format(puzzle_id)

    dim, nv, ng, nz, mirrors, top, bot, left, right = puzzles[puzzle_id]

    sol_path = os.path.join(SOL_DIR, 'solution_{}.txt'.format(puzzle_id))
    assert os.path.exists(sol_path), \
        "Solution file missing: {}".format(sol_path)

    with open(sol_path) as f:
        content = f.read().strip()

    lines = content.split('\n')
    header = lines[0].strip()
    assert header == 'UNDEAD v1 {}'.format(puzzle_id), \
        "Bad header: expected 'UNDEAD v1 {}', got '{}'".format(
            puzzle_id, header)

    grid_lines = lines[1:]
    assert len(grid_lines) == dim, \
        "Expected {} rows, got {}".format(dim, len(grid_lines))

    grid = []
    for r, line in enumerate(grid_lines):
        row = list(line.strip())
        assert len(row) == dim, \
            "Row {}: expected {} chars, got {}".format(r, dim, len(row))
        grid.append(row)

    # Verify mirrors
    for (r, c), m in mirrors.items():
        assert grid[r][c] == m, \
            "Mirror at ({},{}): expected '{}', got '{}'".format(
                r, c, m, grid[r][c])

    # Count monsters
    vc = gc = zc = 0
    for r in range(dim):
        for c in range(dim):
            cell = grid[r][c]
            if (r, c) in mirrors:
                continue
            assert cell in ('V', 'G', 'Z'), \
                "Cell ({},{}): invalid '{}'".format(r, c, cell)
            if cell == 'V':
                vc += 1
            elif cell == 'G':
                gc += 1
            else:
                zc += 1

    assert vc == nv, "Vampires: expected {}, got {}".format(nv, vc)
    assert gc == ng, "Ghosts: expected {}, got {}".format(ng, gc)
    assert zc == nz, "Zombies: expected {}, got {}".format(nz, zc)

    # Verify all sight-line clues
    for c in range(dim):
        actual = trace_line(grid, dim, 0, c, 1, 0)
        assert actual == top[c], \
            "Top clue col {}: expected {}, got {}".format(c, top[c], actual)

    for c in range(dim):
        actual = trace_line(grid, dim, dim - 1, c, -1, 0)
        assert actual == bot[c], \
            "Bottom clue col {}: expected {}, got {}".format(c, bot[c], actual)

    for r in range(dim):
        actual = trace_line(grid, dim, r, 0, 0, 1)
        assert actual == left[r], \
            "Left clue row {}: expected {}, got {}".format(r, left[r], actual)

    for r in range(dim):
        actual = trace_line(grid, dim, r, dim - 1, 0, -1)
        assert actual == right[r], \
            "Right clue row {}: expected {}, got {}".format(r, right[r], actual)


@pytest.mark.parametrize("puzzle_id", [1, 2, 3, 4, 5, 6, 7])
def test_clue_checksum(puzzle_id):
    """Verify solution's clue values match SQLite checksums."""
    sol_path = os.path.join(SOL_DIR, 'solution_{}.txt'.format(puzzle_id))
    assert os.path.exists(sol_path), "Solution file missing"

    with open(sol_path) as f:
        lines = f.read().strip().split('\n')

    grid_lines = lines[1:]
    dim = len(grid_lines)
    grid = [list(line) for line in grid_lines]

    # Compute clue values from solution
    top = [trace_line(grid, dim, 0, c, 1, 0) for c in range(dim)]
    bot = [trace_line(grid, dim, dim - 1, c, -1, 0) for c in range(dim)]
    left = [trace_line(grid, dim, r, 0, 0, 1) for r in range(dim)]
    right = [trace_line(grid, dim, r, dim - 1, 0, -1) for r in range(dim)]

    all_clues = top + bot + left + right
    s = ','.join(str(c) for c in all_clues)
    computed = hashlib.sha256(s.encode()).hexdigest()[:16]

    # Compare against SQLite stored checksum
    conn = sqlite3.connect(META_DB)
    cur = conn.cursor()
    cur.execute('SELECT clue_checksum FROM puzzle_meta WHERE id = ?',
                (puzzle_id,))
    row = cur.fetchone()
    conn.close()

    assert row is not None, "Puzzle {} not in metadata".format(puzzle_id)
    assert computed == row[0], \
        "Clue checksum mismatch for puzzle {}: computed {}, expected {}".format(
            puzzle_id, computed, row[0])


@pytest.mark.parametrize("puzzle_id", [1, 2, 3, 4, 5, 6, 7])
def test_validator_accepts(puzzle_id):
    """Verify the stripped validator binary accepts each solution."""
    sol_path = os.path.join(SOL_DIR, 'solution_{}.txt'.format(puzzle_id))
    assert os.path.exists(sol_path), "Solution file missing"

    result = subprocess.run(
        [VALIDATOR, str(puzzle_id), sol_path],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        "Validator rejected puzzle {} (exit code {})".format(
            puzzle_id, result.returncode)
