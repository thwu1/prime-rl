"""
Test suite for BSP map analyser.
Generates a synthetic WAD file with a known BSP tree, runs the C program
with various queries, and verifies all outputs against a Python reference.
"""


import struct
import subprocess
import os
import re
import random
import tempfile
import pytest

# ===================================================================
# Constants (matching Doom engine definitions)
# ===================================================================

FRACBITS   = 16
FRACUNIT   = 1 << FRACBITS
INT_MIN_32 = -(1 << 31)
INT_MAX_32 = (1 << 31) - 1
ANG45      = 0x20000000
ANG90      = 0x40000000
ANG180     = 0x80000000
ANG270     = 0xC0000000
SLOPERANGE = 2048
NF_SUBSECTOR = 0x8000

FU = FRACUNIT

# ===================================================================
# Utility helpers
# ===================================================================

def to_s32(x):
    x = x & 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x

def to_u32(x):
    return x & 0xFFFFFFFF

def c_trunc_div(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q

# ===================================================================
# tantoangle table loader
# ===================================================================

_tantoangle = None

def load_tantoangle():
    global _tantoangle
    if _tantoangle is not None:
        return _tantoangle
    with open('/app/tantoangle_lut.h', 'r') as f:
        content = f.read()
    m = re.search(r'tantoangle\[\d+\]\s*=\s*\{([^}]+)\}', content, re.DOTALL)
    assert m, "Could not parse tantoangle table"
    nums = re.findall(r'\d+', m.group(1))
    _tantoangle = [int(x) for x in nums]
    assert len(_tantoangle) == 2049
    return _tantoangle

# ===================================================================
# Reference implementations (matching Doom engine exactly)
# ===================================================================

def ref_fixed_mul(a, b):
    return to_s32((a * b) >> FRACBITS)

def ref_fixed_div(a, b):
    assert b != 0
    if (abs(a) >> 14) >= abs(b):
        return INT_MIN_32 if (a ^ b) < 0 else INT_MAX_32
    result = c_trunc_div(a << FRACBITS, b)
    return to_s32(result)

def ref_lump_hash(s):
    h = 5381
    for i in range(min(len(s), 8)):
        if s[i] == '\0':
            break
        h = ((h << 5) ^ h) ^ ord(s[i].upper())
        h &= 0xFFFFFFFF
    return h

def ref_slope_div(num, den):
    num, den = num & 0xFFFFFFFF, den & 0xFFFFFFFF
    if den < 512:
        return SLOPERANGE
    ans = ((num << 3) & 0xFFFFFFFF) // (den >> 8)
    return ans if ans <= SLOPERANGE else SLOPERANGE

def ref_point_on_side(px, py, nx, ny, ndx, ndy):
    if ndx == 0:
        return (1 if ndy > 0 else 0) if px <= nx else (1 if ndy < 0 else 0)
    if ndy == 0:
        return (1 if ndx < 0 else 0) if py <= ny else (1 if ndx > 0 else 0)
    dx = to_s32(px - nx)
    dy = to_s32(py - ny)
    if (ndy ^ ndx ^ dx ^ dy) & 0x80000000:
        return 1 if (ndy ^ dx) & 0x80000000 else 0
    left  = ref_fixed_mul(ndy >> FRACBITS, dx)
    right = ref_fixed_mul(dy, ndx >> FRACBITS)
    return 0 if right < left else 1

def ref_point_to_angle2(x1, y1, x2, y2):
    tbl = load_tantoangle()
    x, y = to_s32(x2 - x1), to_s32(y2 - y1)
    if x == 0 and y == 0:
        return 0
    if x >= 0:
        if y >= 0:
            if x > y:
                return to_u32(tbl[ref_slope_div(y, x)])
            else:
                return to_u32(ANG90 - 1 - tbl[ref_slope_div(x, y)])
        else:
            y = -y
            if x > y:
                return to_u32(-tbl[ref_slope_div(y, x)])
            else:
                return to_u32(ANG270 + tbl[ref_slope_div(x, y)])
    else:
        x = -x
        if y >= 0:
            if x > y:
                return to_u32(ANG180 - 1 - tbl[ref_slope_div(y, x)])
            else:
                return to_u32(ANG90 + tbl[ref_slope_div(x, y)])
        else:
            y = -y
            if x > y:
                return to_u32(ANG180 + tbl[ref_slope_div(y, x)])
            else:
                return to_u32(ANG270 - 1 - tbl[ref_slope_div(x, y)])
    return 0

def ref_directory_hash(entries):
    """FNV-1a (32-bit) over WAD directory entries."""
    FNV_OFFSET = 2166136261
    FNV_PRIME = 16777619
    h = FNV_OFFSET
    for filepos, size, name_bytes in entries:
        # filepos as 4 LE bytes
        fp = filepos & 0xFFFFFFFF
        for b in range(4):
            h ^= (fp >> (b * 8)) & 0xFF
            h = (h * FNV_PRIME) & 0xFFFFFFFF
        # size as 4 LE bytes
        sz = size & 0xFFFFFFFF
        for b in range(4):
            h ^= (sz >> (b * 8)) & 0xFF
            h = (h * FNV_PRIME) & 0xFFFFFFFF
        # name as 8 raw bytes
        name_padded = name_bytes[:8].ljust(8, b'\x00')
        for byte_val in name_padded:
            h ^= byte_val
            h = (h * FNV_PRIME) & 0xFFFFFFFF
    return h

# ===================================================================
# BSP tree definition (5 nodes, 6 subsectors)
# ===================================================================
# Tree layout:
#                Node 4 (root, horizontal y=0)
#               /                              \
#          Node 2 (vertical x=0, bottom)   Node 3 (vertical x=0, top)
#         /           \                   /           \
#    Node 0 (diag)  Node 1 (diag)      SS4           SS5
#    /      \       /      \
#  SS0     SS1    SS2     SS3

MAP_NODES = [
    # Node 0: diagonal partition at (64, -64), direction (32, 32)
    {'x': 64, 'y': -64, 'dx': 32, 'dy': 32,
     'bbox': [[0, -128, 64, 192], [0, -128, -64, 64]],
     'children': [NF_SUBSECTOR | 0, NF_SUBSECTOR | 1]},
    # Node 1: diagonal partition at (-64, -64), direction (-32, 32)
    {'x': -64, 'y': -64, 'dx': -32, 'dy': 32,
     'bbox': [[0, -128, -192, -64], [0, -128, -64, 64]],
     'children': [NF_SUBSECTOR | 2, NF_SUBSECTOR | 3]},
    # Node 2: vertical partition at (0, -64), direction (0, 64)
    {'x': 0, 'y': -64, 'dx': 0, 'dy': 64,
     'bbox': [[0, -128, 0, 192], [0, -128, -192, 0]],
     'children': [0, 1]},
    # Node 3: vertical partition at (0, 64), direction (0, 64)
    {'x': 0, 'y': 64, 'dx': 0, 'dy': 64,
     'bbox': [[128, 0, 0, 192], [128, 0, -192, 0]],
     'children': [NF_SUBSECTOR | 4, NF_SUBSECTOR | 5]},
    # Node 4 (root): horizontal partition at (0, 0), direction (64, 0)
    {'x': 0, 'y': 0, 'dx': 64, 'dy': 0,
     'bbox': [[0, -128, -192, 192], [128, 0, -192, 192]],
     'children': [2, 3]},
]

MAP_SUBSECTORS = [
    {'numsegs': 1, 'firstseg': i} for i in range(6)
]

NUM_NODES = len(MAP_NODES)
NUM_SS    = len(MAP_SUBSECTORS)

def nodes_as_fixed():
    """Return nodes with coordinates in 16.16 fixed-point."""
    out = []
    for n in MAP_NODES:
        out.append({
            'x': n['x'] << FRACBITS, 'y': n['y'] << FRACBITS,
            'dx': n['dx'] << FRACBITS, 'dy': n['dy'] << FRACBITS,
            'bbox': [[(v << FRACBITS) for v in row] for row in n['bbox']],
            'children': list(n['children']),
        })
    return out

# ===================================================================
# Reference BSP operations using the loaded tree
# ===================================================================

def ref_bsp_locate(x, y):
    nodes = nodes_as_fixed()
    nodenum = NUM_NODES - 1
    while not (nodenum & NF_SUBSECTOR):
        nd = nodes[nodenum]
        side = ref_point_on_side(x, y, nd['x'], nd['y'], nd['dx'], nd['dy'])
        nodenum = nd['children'][side]
    if nodenum == -1:
        return 0
    return nodenum & ~NF_SUBSECTOR

def ref_bsp_traverse(x, y):
    nodes = nodes_as_fixed()
    result = []
    def walk(bspnum):
        if bspnum & NF_SUBSECTOR:
            ssnum = 0 if bspnum == -1 else (bspnum & ~NF_SUBSECTOR)
            result.append(ssnum)
            return
        nd = nodes[bspnum]
        side = ref_point_on_side(x, y, nd['x'], nd['y'], nd['dx'], nd['dy'])
        walk(nd['children'][side])        # front first
        walk(nd['children'][side ^ 1])    # then back
    walk(NUM_NODES - 1)
    return result

# ===================================================================
# WAD file generator
# ===================================================================

WAD_PATH   = '/tmp/test_bsp.wad'
QUERY_PATH = '/tmp/test_queries.txt'
OUT_PATH   = '/tmp/test_output.txt'
BINARY     = '/app/bsp_resolver'

# Track WAD directory entries for DIRHASH verification
WAD_DIR_ENTRIES = []

def generate_wad():
    """Create a PWAD containing NODES and SSECTORS lumps."""
    global WAD_DIR_ENTRIES

    # Pack NODES lump
    nodes_bytes = b''
    for nd in MAP_NODES:
        # int16: x, y, dx, dy
        nodes_bytes += struct.pack('<4h', nd['x'], nd['y'], nd['dx'], nd['dy'])
        # int16: bbox[2][4]
        for c in range(2):
            for b in range(4):
                nodes_bytes += struct.pack('<h', nd['bbox'][c][b])
        # uint16: children[2]
        nodes_bytes += struct.pack('<2H', nd['children'][0], nd['children'][1])

    # Pack SSECTORS lump
    ss_bytes = b''
    for ss in MAP_SUBSECTORS:
        ss_bytes += struct.pack('<2H', ss['numsegs'], ss['firstseg'])

    # Layout: header(12) + NODES data + SSECTORS data + directory
    nodes_off = 12
    ss_off    = nodes_off + len(nodes_bytes)
    dir_off   = ss_off + len(ss_bytes)

    # Directory entries (MAP01 label + NODES + SSECTORS)
    entries = [
        (nodes_off, 0,                b'MAP01\x00\x00\x00'),
        (nodes_off, len(nodes_bytes), b'NODES\x00\x00\x00'),
        (ss_off,    len(ss_bytes),    b'SSECTORS'),
    ]

    WAD_DIR_ENTRIES = entries

    # Header: "PWAD", numlumps, infotableofs (all little-endian)
    header = b'PWAD'
    header += struct.pack('<i', len(entries))
    header += struct.pack('<i', dir_off)

    # Directory
    dir_bytes = b''
    for filepos, size, name in entries:
        dir_bytes += struct.pack('<i', filepos)
        dir_bytes += struct.pack('<i', size)
        dir_bytes += name[:8].ljust(8, b'\x00')

    with open(WAD_PATH, 'wb') as f:
        f.write(header)
        f.write(nodes_bytes)
        f.write(ss_bytes)
        f.write(dir_bytes)

# ===================================================================
# Runner helper
# ===================================================================

def run_queries(queries):
    """Write queries, run the binary, return output lines."""
    with open(QUERY_PATH, 'w') as f:
        for q in queries:
            f.write(q + '\n')

    r = subprocess.run(
        [BINARY, WAD_PATH, QUERY_PATH, OUT_PATH],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, \
        f"Program exited with code {r.returncode}:\n{r.stderr}"

    with open(OUT_PATH) as f:
        return [l.strip() for l in f if l.strip()]

# ===================================================================
# pytest fixtures
# ===================================================================

@pytest.fixture(scope='module', autouse=True)
def setup_wad():
    generate_wad()

@pytest.fixture(scope='module')
def built():
    r = subprocess.run(
        ['make', '-C', '/app', '-j1'],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, \
        f"Build failed:\n{r.stdout}\n{r.stderr}"
    return True

# ===================================================================
# Tests
# ===================================================================

class TestBuild:
    def test_make_succeeds(self, built):
        """The project must compile without errors."""
        pass


class TestFixedMath:
    def test_mul(self, built):
        cases = [
            (0, 0), (FU, FU), (FU, 0), (FU, -FU), (-FU, -FU),
            (2*FU, 3*FU), (32767*FU, 2),
        ]
        rng = random.Random(200)
        for _ in range(40):
            a = rng.randint(-100_000_000, 100_000_000)
            b = rng.randint(-100_000_000, 100_000_000)
            cases.append((a, b))

        queries  = [f"MUL {a} {b}" for a, b in cases]
        expected = [str(ref_fixed_mul(a, b)) for a, b in cases]
        actual   = run_queries(queries)
        self._compare(queries, expected, actual)

    def test_div(self, built):
        cases = [
            (FU, FU), (3*FU, 2*FU), (-FU, FU), (FU, -FU), (0, FU),
        ]
        # Overflow boundary tests (>>14 vs >>15 threshold)
        for a_val in [16384, 16385, 20000, 30000, 32767]:
            cases += [(a_val, 1), (-a_val, 1)]
        for b_val in [2, 3, 5, 10, 100]:
            a_val = b_val * 16384
            if abs(a_val) <= 1_000_000_000:
                cases += [(a_val, b_val), (a_val + 1, b_val)]
        # Sign-swap tests
        cases += [
            (1_000_000_000, 1), (-1_000_000_000, 1),
            (1_000_000_000, -1), (-1_000_000_000, -1),
        ]
        rng = random.Random(201)
        for _ in range(30):
            a = rng.randint(-100_000_000, 100_000_000)
            b = rng.randint(1, 100_000_000) * rng.choice([-1, 1])
            cases.append((a, b))

        queries  = [f"DIV {a} {b}" for a, b in cases]
        expected = [str(ref_fixed_div(a, b)) for a, b in cases]
        actual   = run_queries(queries)
        self._compare(queries, expected, actual)

    @staticmethod
    def _compare(queries, expected, actual):
        assert len(actual) == len(expected), \
            f"Line count mismatch: expected {len(expected)}, got {len(actual)}"
        fails = []
        for i, (q, e, a) in enumerate(zip(queries, expected, actual)):
            if a != e:
                fails.append(f"  [{q}]: expected {e}, got {a}")
        if fails:
            msg = f"{len(fails)} failures:\n" + '\n'.join(fails[:20])
            pytest.fail(msg)


class TestHash:
    def test_lump_names(self, built):
        names = [
            "PLAYPAL", "COLORMAP", "ENDOOM", "DEMO1", "DEMO2",
            "E1M1", "MAP01", "THINGS", "LINEDEFS", "VERTEXES",
            "NODES", "SECTORS", "SSECTORS", "TEXTURE1", "PNAMES",
            "GENMIDI", "FLOOR4_8", "CEIL3_5", "STEP2",
            "A", "AB", "ABCDEFGH", "abcdefgh", "a",
        ]
        rng = random.Random(202)
        for _ in range(20):
            length = rng.randint(1, 8)
            names.append(''.join(rng.choice(
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_') for _ in range(length)))

        queries  = [f"HASH {n}" for n in names]
        expected = [str(ref_lump_hash(n)) for n in names]
        actual   = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(f"  [{q}]: exp {e}, got {a}" for q, e, a in fails[:15])
            pytest.fail(f"{len(fails)} HASH failures:\n{detail}")


class TestSide:
    def test_axis_aligned(self, built):
        cases = [
            (0, 0, FU, 0, 0, FU),
            (2*FU, 0, FU, 0, 0, FU),
            (0, 0, FU, 0, 0, -FU),
            (2*FU, 0, FU, 0, 0, -FU),
            (0, 0, 0, FU, FU, 0),
            (0, 2*FU, 0, FU, FU, 0),
            (0, 0, 0, FU, -FU, 0),
            (0, 2*FU, 0, FU, -FU, 0),
        ]
        self._run_side(cases, built)

    def test_sign_bit_fast_path(self, built):
        """Cases where (ndy^dx) differs from (ndx^dy) in the sign bit."""
        cases = [
            (FU, -FU, 0, 0, FU, FU),
            (-FU, FU, 0, 0, FU, FU),
            (FU, -FU, 0, 0, -FU, FU),
            (-FU, FU, 0, 0, -FU, -FU),
            (-FU, -FU, 0, 0, FU, -FU),
            (10*FU, -5*FU, 3*FU, 2*FU, 4*FU, 7*FU),
            (-10*FU, 5*FU, -3*FU, -2*FU, -4*FU, 7*FU),
        ]
        self._run_side(cases, built)

    def test_cross_product_path(self, built):
        cases = [
            (2*FU, 3*FU, 0, 0, FU, FU),
            (3*FU, 2*FU, 0, 0, FU, FU),
        ]
        rng = random.Random(203)
        for _ in range(40):
            px  = rng.randint(-20, 20) * FU
            py  = rng.randint(-20, 20) * FU
            nx  = rng.randint(-10, 10) * FU
            ny  = rng.randint(-10, 10) * FU
            ndx = rng.randint(-10, 10) * FU
            ndy = rng.randint(-10, 10) * FU
            if ndx == 0 and ndy == 0:
                continue
            cases.append((px, py, nx, ny, ndx, ndy))
        self._run_side(cases, built)

    def _run_side(self, cases, built):
        queries  = [f"SIDE {a} {b} {c} {d} {e} {f}" for a, b, c, d, e, f in cases]
        expected = [str(ref_point_on_side(*c)) for c in cases]
        actual   = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(f"  [{q}]: exp {e}, got {a}" for q, e, a in fails[:15])
            pytest.fail(f"{len(fails)} SIDE failures:\n{detail}")


class TestAngle:
    def test_all_octants(self, built):
        cases = [
            (0, 0, 2000, 1000),     # oct 0
            (0, 0, 1000, 2000),     # oct 1
            (0, 0, -1000, 2000),    # oct 2
            (0, 0, -2000, 1000),    # oct 3
            (0, 0, -2000, -1000),   # oct 4
            (0, 0, -1000, -2000),   # oct 5
            (0, 0, 1000, -2000),    # oct 6
            (0, 0, 2000, -1000),    # oct 7
        ]
        self._run_angle(cases, built)

    def test_cardinals_diagonals(self, built):
        cases = [
            (0, 0, 1000, 0), (0, 0, 0, 1000),
            (0, 0, -1000, 0), (0, 0, 0, -1000),
            (0, 0, 1000, 1000), (0, 0, -1000, 1000),
            (0, 0, -1000, -1000), (0, 0, 1000, -1000),
            (100, 200, 100, 200),   # degenerate (same point)
        ]
        self._run_angle(cases, built)

    def test_slopediv_boundary(self, built):
        """SlopeDiv with den in [256, 511] — distinguishes < 256 vs < 512."""
        cases = [
            (0, 0, 300, 100), (0, 0, 400, 150),
            (0, 0, 500, 200), (0, 0, 256, 100),
            (0, 0, 511, 200), (0, 0, -300, 100),
            (0, 0, -300, -100), (0, 0, 300, -100),
        ]
        self._run_angle(cases, built)

    def test_octant5_edge(self, built):
        """Octant 5 cases — ANG270+1+ vs ANG270-1-."""
        cases = [
            (0, 0, -100, -200),
            (0, 0, -500, -1000),
            (0, 0, -1, -2),
            (100, 200, -400, -600),
        ]
        self._run_angle(cases, built)

    def test_random_angles(self, built):
        rng = random.Random(204)
        cases = []
        for _ in range(50):
            x1 = rng.randint(-10000, 10000)
            y1 = rng.randint(-10000, 10000)
            x2 = rng.randint(-10000, 10000)
            y2 = rng.randint(-10000, 10000)
            if x1 == x2 and y1 == y2:
                x2 += 1
            cases.append((x1, y1, x2, y2))
        for _ in range(30):
            x1 = rng.randint(-100, 100) * FU
            y1 = rng.randint(-100, 100) * FU
            x2 = rng.randint(-100, 100) * FU
            y2 = rng.randint(-100, 100) * FU
            if x1 == x2 and y1 == y2:
                x2 += FU
            cases.append((x1, y1, x2, y2))
        self._run_angle(cases, built)

    def _run_angle(self, cases, built):
        queries  = [f"ANGLE {a} {b} {c} {d}" for a, b, c, d in cases]
        expected = [str(ref_point_to_angle2(*c)) for c in cases]
        actual   = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(f"  [{q}]: exp {e}, got {a}" for q, e, a in fails[:15])
            pytest.fail(f"{len(fails)} ANGLE failures:\n{detail}")


class TestLocate:
    """LOCATE queries depend on correct WAD parsing + BSP math."""

    def test_quadrant_points(self, built):
        """Points clearly inside each quadrant."""
        cases = [
            # Bottom-right area -> SS0
            (100 * FU, -100 * FU, 0),
            # Bottom-left area -> SS2 or SS3 (depending on diagonal)
            (-100 * FU, -100 * FU, None),
            # Top-right area -> SS4
            (100 * FU, 100 * FU, 4),
            # Top-left area -> SS5
            (-100 * FU, 100 * FU, 5),
        ]
        queries, expected = [], []
        for x, y, exp in cases:
            queries.append(f"LOCATE {x} {y}")
            if exp is None:
                exp = ref_bsp_locate(x, y)
            expected.append(str(exp))

        actual = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(f"  [{q}]: exp {e}, got {a}" for q, e, a in fails)
            pytest.fail(f"{len(fails)} LOCATE failures:\n{detail}")

    def test_diagonal_boundary(self, built):
        """Point near diagonal partition that exercises cross-product path
        and is sensitive to the FRACBITS-1 vs FRACBITS shift bug."""
        # This specific point gives different results with half-scale vs
        # full-scale node coordinates because it changes which code path
        # (sign-bit vs cross-product) is taken at node 0.
        x, y = 4500000, -3500000
        exp = ref_bsp_locate(x, y)
        actual = run_queries([f"LOCATE {x} {y}"])
        assert actual[0] == str(exp), \
            f"LOCATE {x} {y}: expected SS{exp}, got SS{actual[0]}"

    def test_random_locate(self, built):
        rng = random.Random(205)
        queries, expected = [], []
        for _ in range(30):
            x = rng.randint(-150, 150) * FU
            y = rng.randint(-150, 150) * FU
            queries.append(f"LOCATE {x} {y}")
            expected.append(str(ref_bsp_locate(x, y)))
        actual = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(f"  [{q}]: exp {e}, got {a}" for q, e, a in fails[:15])
            pytest.fail(f"{len(fails)} LOCATE failures:\n{detail}")


class TestTraverse:
    """TRAVERSE queries verify front-to-back BSP visitation order."""

    def test_bottom_right_viewpoint(self, built):
        x, y = 100 * FU, -100 * FU
        exp = ref_bsp_traverse(x, y)
        actual = run_queries([f"TRAVERSE {x} {y}"])
        exp_str = ','.join(str(s) for s in exp)
        assert actual[0] == exp_str, \
            f"TRAVERSE {x} {y}: expected [{exp_str}], got [{actual[0]}]"

    def test_top_left_viewpoint(self, built):
        x, y = -100 * FU, 100 * FU
        exp = ref_bsp_traverse(x, y)
        actual = run_queries([f"TRAVERSE {x} {y}"])
        exp_str = ','.join(str(s) for s in exp)
        assert actual[0] == exp_str, \
            f"TRAVERSE {x} {y}: expected [{exp_str}], got [{actual[0]}]"

    def test_multiple_viewpoints(self, built):
        viewpoints = [
            (50 * FU, 50 * FU),
            (-50 * FU, -50 * FU),
            (0, 0),
            (1 * FU, -1 * FU),
            (-200 * FU, -200 * FU),
        ]
        queries, expected = [], []
        for x, y in viewpoints:
            queries.append(f"TRAVERSE {x} {y}")
            order = ref_bsp_traverse(x, y)
            expected.append(','.join(str(s) for s in order))

        actual = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(
                f"  [{q}]: exp [{e}], got [{a}]" for q, e, a in fails)
            pytest.fail(f"{len(fails)} TRAVERSE failures:\n{detail}")

    def test_random_traversals(self, built):
        rng = random.Random(206)
        queries, expected = [], []
        for _ in range(20):
            x = rng.randint(-200, 200) * FU
            y = rng.randint(-200, 200) * FU
            queries.append(f"TRAVERSE {x} {y}")
            order = ref_bsp_traverse(x, y)
            expected.append(','.join(str(s) for s in order))
        actual = run_queries(queries)
        assert len(actual) == len(expected)
        fails = [(q, e, a) for q, e, a in zip(queries, expected, actual) if a != e]
        if fails:
            detail = '\n'.join(
                f"  [{q}]: exp [{e}], got [{a}]" for q, e, a in fails[:10])
            pytest.fail(f"{len(fails)} TRAVERSE failures:\n{detail}")


class TestDirHash:
    """DIRHASH queries verify WAD directory hashing over all entries."""

    def test_dirhash_basic(self, built):
        """DIRHASH must return the correct FNV-1a hash of the WAD directory."""
        expected = ref_directory_hash(WAD_DIR_ENTRIES)
        actual = run_queries(["DIRHASH"])
        assert actual[0] == str(expected), \
            f"DIRHASH: expected {expected}, got {actual[0]}"

    def test_dirhash_not_zero(self, built):
        """DIRHASH must not return stub value 0."""
        actual = run_queries(["DIRHASH"])
        assert actual[0] != "0", \
            "DIRHASH returned 0 — stub has not been implemented"

    def test_dirhash_not_fnv_empty(self, built):
        """DIRHASH must not return FNV offset basis (empty directory hash)."""
        actual = run_queries(["DIRHASH"])
        assert actual[0] != "2166136261", \
            "DIRHASH returned FNV offset basis — directory data was not available"

    def test_dirhash_repeated(self, built):
        """DIRHASH must be deterministic across repeated calls."""
        actual = run_queries(["DIRHASH", "DIRHASH", "DIRHASH"])
        assert len(actual) == 3
        assert actual[0] == actual[1] == actual[2], \
            f"DIRHASH not deterministic: {actual}"
