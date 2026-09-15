"""

Independent reference implementation and tests for Rubik's Cube
group-theoretic state analysis.
"""
import json
import os
import pytest
from math import gcd
from functools import reduce


# ================================================================
# Reference Implementation — Cubie-Level Rubik's Cube Algebra
# ================================================================

# Facelet indices for each corner position (3 facelets per corner)
# Corners: URF=0 UFL=1 ULB=2 UBR=3 DFR=4 DLF=5 DBL=6 DRB=7
_CORNER_FACELETS = [
    [8, 9, 20],    # URF: U9 R1 F3
    [6, 18, 38],   # UFL: U7 F1 L3
    [0, 36, 47],   # ULB: U1 L1 B3
    [2, 45, 11],   # UBR: U3 B1 R3
    [29, 26, 15],  # DFR: D3 F9 R7
    [27, 44, 24],  # DLF: D1 L9 F7
    [33, 53, 42],  # DBL: D7 B9 L7
    [35, 17, 51],  # DRB: D9 R9 B7
]

# Facelet indices for each edge position (2 facelets per edge)
# Edges: UR=0 UF=1 UL=2 UB=3 DR=4 DF=5 DL=6 DB=7 FR=8 FL=9 BL=10 BR=11
_EDGE_FACELETS = [
    [5, 10],   # UR: U6 R2
    [7, 19],   # UF: U8 F2
    [3, 37],   # UL: U4 L2
    [1, 46],   # UB: U2 B2
    [32, 16],  # DR: D6 R8
    [28, 25],  # DF: D2 F8
    [30, 43],  # DL: D4 L8
    [34, 52],  # DB: D8 B8
    [23, 12],  # FR: F6 R4
    [21, 41],  # FL: F4 L6
    [50, 39],  # BL: B6 L4
    [48, 14],  # BR: B4 R6
]

# Color at each facelet of each corner (U=0 R=1 F=2 D=3 L=4 B=5)
_CORNER_COLORS = [
    [0, 1, 2],  # URF
    [0, 2, 4],  # UFL
    [0, 4, 5],  # ULB
    [0, 5, 1],  # UBR
    [3, 2, 1],  # DFR
    [3, 4, 2],  # DLF
    [3, 5, 4],  # DBL
    [3, 1, 5],  # DRB
]

# Color at each facelet of each edge
_EDGE_COLORS = [
    [0, 1],  # UR
    [0, 2],  # UF
    [0, 4],  # UL
    [0, 5],  # UB
    [3, 1],  # DR
    [3, 2],  # DF
    [3, 4],  # DL
    [3, 5],  # DB
    [2, 1],  # FR
    [2, 4],  # FL
    [5, 4],  # BL
    [5, 1],  # BR
]

_COLOR_CHARS = "URFDLB"

# Six basic face moves: (corner_perm, corner_ori, edge_perm, edge_ori)
# In "is replaced by" convention: perm[position] = which cubie now sits there
_BASIC_MOVES = {
    "U": (
        [3, 0, 1, 2, 4, 5, 6, 7],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [3, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    "R": (
        [4, 1, 2, 0, 7, 5, 6, 3],
        [2, 0, 0, 1, 1, 0, 0, 2],
        [8, 1, 2, 3, 11, 5, 6, 7, 4, 9, 10, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    "F": (
        [1, 5, 2, 3, 0, 4, 6, 7],
        [1, 2, 0, 0, 2, 1, 0, 0],
        [0, 9, 2, 3, 4, 8, 6, 7, 1, 5, 10, 11],
        [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0],
    ),
    "D": (
        [0, 1, 2, 3, 5, 6, 7, 4],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 1, 2, 3, 5, 6, 7, 4, 8, 9, 10, 11],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    "L": (
        [0, 2, 6, 3, 4, 1, 5, 7],
        [0, 1, 2, 0, 0, 2, 1, 0],
        [0, 1, 10, 3, 4, 5, 9, 7, 8, 2, 6, 11],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    "B": (
        [0, 1, 3, 7, 4, 5, 2, 6],
        [0, 0, 1, 2, 0, 0, 2, 1],
        [0, 1, 2, 11, 4, 5, 6, 10, 8, 9, 3, 7],
        [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1],
    ),
}


def _make_identity():
    """Return the identity cube state."""
    return (list(range(8)), [0] * 8, list(range(12)), [0] * 12)


def _compose(state_a, state_b):
    """Compose two cube states: result represents applying B then A."""
    cp_a, co_a, ep_a, eo_a = state_a
    cp_b, co_b, ep_b, eo_b = state_b
    new_cp = [cp_a[cp_b[i]] for i in range(8)]
    new_co = [(co_a[cp_b[i]] + co_b[i]) % 3 for i in range(8)]
    new_ep = [ep_a[ep_b[i]] for i in range(12)]
    new_eo = [(eo_a[ep_b[i]] + eo_b[i]) % 2 for i in range(12)]
    return (new_cp, new_co, new_ep, new_eo)


def _state_to_facelet_string(state):
    """Convert cubie state to 54-character facelet string."""
    cp, co, ep, eo = state
    facelets = [0] * 54
    # Center facelets
    for face_idx in range(6):
        facelets[face_idx * 9 + 4] = face_idx
    # Corner facelets
    for pos in range(8):
        cubie = cp[pos]
        twist = co[pos]
        for k in range(3):
            facelet_idx = _CORNER_FACELETS[pos][(k + twist) % 3]
            facelets[facelet_idx] = _CORNER_COLORS[cubie][k]
    # Edge facelets
    for pos in range(12):
        cubie = ep[pos]
        flip = eo[pos]
        for k in range(2):
            facelet_idx = _EDGE_FACELETS[pos][(k + flip) % 2]
            facelets[facelet_idx] = _EDGE_COLORS[cubie][k]
    return "".join(_COLOR_CHARS[c] for c in facelets)


def _compute_twist(corner_orientations):
    """Base-3 encoding of first 7 corner orientations."""
    val = 0
    for i in range(7):
        val = 3 * val + corner_orientations[i]
    return val


def _compute_flip(edge_orientations):
    """Base-2 encoding of first 11 edge orientations."""
    val = 0
    for i in range(11):
        val = 2 * val + edge_orientations[i]
    return val


def _compute_corners_coord(corner_perm):
    """Corner permutation coordinate via rotate-left Lehmer code."""
    perm = list(corner_perm)
    b = 0
    for j in range(7, 0, -1):
        k = 0
        while perm[j] != j:
            # Rotate perm[0..j] left by one position
            temp = perm[0]
            for idx in range(j):
                perm[idx] = perm[idx + 1]
            perm[j] = temp
            k += 1
        b = (j + 1) * b + k
    return b


def _compute_order(state):
    """Compute the order of the group element via cycle decomposition."""
    cp, co, ep, eo = state

    cycle_contributions = []

    # Corner cycles
    seen = [False] * 8
    for start in range(8):
        if seen[start]:
            continue
        length = 0
        ori_total = 0
        cur = start
        while not seen[cur]:
            seen[cur] = True
            ori_total += co[cur]
            cur = cp[cur]
            length += 1
        if ori_total % 3 != 0:
            cycle_contributions.append(3 * length)
        else:
            cycle_contributions.append(length)

    # Edge cycles
    seen = [False] * 12
    for start in range(12):
        if seen[start]:
            continue
        length = 0
        ori_total = 0
        cur = start
        while not seen[cur]:
            seen[cur] = True
            ori_total += eo[cur]
            cur = ep[cur]
            length += 1
        if ori_total % 2 != 0:
            cycle_contributions.append(2 * length)
        else:
            cycle_contributions.append(length)

    def lcm(a, b):
        return a * b // gcd(a, b)

    return reduce(lcm, cycle_contributions, 1)


def _parse_scramble(line):
    """Parse a scramble line and return the resulting cube state."""
    state = _make_identity()
    tokens = line.strip().split()
    for token in tokens:
        if not token:
            continue
        face = token[0]
        if len(token) == 1:
            repeats = 1
        elif token[1] == "'":
            repeats = 3
        elif token[1] == "2":
            repeats = 2
        else:
            repeats = 1
        base = _BASIC_MOVES[face]
        for _ in range(repeats):
            state = _compose(state, base)
    return state


def _compute_expected_results():
    """Read scrambles and compute all expected values."""
    with open("/app/scrambles.txt") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    results = []
    for line in lines:
        st = _parse_scramble(line)
        cp, co, ep, eo = st
        results.append({
            "facelet_string": _state_to_facelet_string(st),
            "twist": _compute_twist(co),
            "flip": _compute_flip(eo),
            "corners": _compute_corners_coord(cp),
            "order": _compute_order(st),
        })
    return results


# Pre-compute expected values at import time
_EXPECTED = _compute_expected_results()


def _load_agent_results():
    with open("/app/results.json") as f:
        return json.load(f)


# ================================================================
# Self-Tests for Reference Implementation
# ================================================================

class TestReferenceIntegrity:
    """Verify that the reference implementation is internally correct."""

    def test_identity_produces_solved_facelet(self):
        fs = _state_to_facelet_string(_make_identity())
        assert fs == "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

    def test_identity_has_zero_coordinates(self):
        s = _make_identity()
        assert _compute_twist(s[1]) == 0
        assert _compute_flip(s[3]) == 0
        assert _compute_corners_coord(s[0]) == 0

    def test_identity_has_order_1(self):
        assert _compute_order(_make_identity()) == 1

    def test_single_move_r4_is_identity(self):
        s = _make_identity()
        r = _BASIC_MOVES["R"]
        for _ in range(4):
            s = _compose(s, r)
        assert s == _make_identity()

    def test_single_move_u4_is_identity(self):
        s = _make_identity()
        u = _BASIC_MOVES["U"]
        for _ in range(4):
            s = _compose(s, u)
        assert s == _make_identity()

    def test_single_move_f4_is_identity(self):
        s = _make_identity()
        f = _BASIC_MOVES["F"]
        for _ in range(4):
            s = _compose(s, f)
        assert s == _make_identity()

    def test_r_then_rprime_is_identity(self):
        r = _BASIC_MOVES["R"]
        rprime = _compose(_compose(r, r), r)  # R^3 = R'
        result = _compose(r, rprime)
        assert result == _make_identity()

    def test_sexy_move_has_order_6(self):
        s = _parse_scramble("R U R' U'")
        assert _compute_order(s) == 6

    def test_twist_range(self):
        for exp in _EXPECTED:
            assert 0 <= exp["twist"] <= 2186

    def test_flip_range(self):
        for exp in _EXPECTED:
            assert 0 <= exp["flip"] <= 2047

    def test_corners_range(self):
        for exp in _EXPECTED:
            assert 0 <= exp["corners"] <= 40319

    def test_facelet_color_counts(self):
        for exp in _EXPECTED:
            fs = exp["facelet_string"]
            assert len(fs) == 54
            for c in "URFDLB":
                assert fs.count(c) == 9


# ================================================================
# Agent Output Tests
# ================================================================

class TestAgentResults:
    """Verify the agent's results.json against reference computation."""

    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), \
            "/app/results.json not found"

    def test_results_is_valid_json_list(self):
        data = _load_agent_results()
        assert isinstance(data, list), "results.json must be a JSON array"

    def test_results_has_five_entries(self):
        data = _load_agent_results()
        assert len(data) == 5, f"Expected 5 results, got {len(data)}"

    def test_results_have_required_keys(self):
        data = _load_agent_results()
        required = {"facelet_string", "twist", "flip", "corners", "order"}
        for i, entry in enumerate(data):
            missing = required - set(entry.keys())
            assert not missing, f"Result {i} missing keys: {missing}"

    @pytest.mark.parametrize("idx", range(5))
    def test_facelet_string(self, idx):
        agent = _load_agent_results()
        assert str(agent[idx]["facelet_string"]) == _EXPECTED[idx]["facelet_string"], \
            f"Scramble {idx}: expected facelet {_EXPECTED[idx]['facelet_string']}, " \
            f"got {agent[idx]['facelet_string']}"

    @pytest.mark.parametrize("idx", range(5))
    def test_facelet_validity(self, idx):
        agent = _load_agent_results()
        fs = str(agent[idx]["facelet_string"])
        assert len(fs) == 54, f"Scramble {idx}: length {len(fs)} != 54"
        for c in "URFDLB":
            assert fs.count(c) == 9, \
                f"Scramble {idx}: color {c} appears {fs.count(c)} times, expected 9"

    @pytest.mark.parametrize("idx", range(5))
    def test_twist(self, idx):
        agent = _load_agent_results()
        assert int(agent[idx]["twist"]) == _EXPECTED[idx]["twist"], \
            f"Scramble {idx}: twist expected {_EXPECTED[idx]['twist']}, " \
            f"got {agent[idx]['twist']}"

    @pytest.mark.parametrize("idx", range(5))
    def test_flip(self, idx):
        agent = _load_agent_results()
        assert int(agent[idx]["flip"]) == _EXPECTED[idx]["flip"], \
            f"Scramble {idx}: flip expected {_EXPECTED[idx]['flip']}, " \
            f"got {agent[idx]['flip']}"

    @pytest.mark.parametrize("idx", range(5))
    def test_corners(self, idx):
        agent = _load_agent_results()
        assert int(agent[idx]["corners"]) == _EXPECTED[idx]["corners"], \
            f"Scramble {idx}: corners expected {_EXPECTED[idx]['corners']}, " \
            f"got {agent[idx]['corners']}"

    @pytest.mark.parametrize("idx", range(5))
    def test_order(self, idx):
        agent = _load_agent_results()
        n = int(agent[idx]["order"])
        assert n == _EXPECTED[idx]["order"], \
            f"Scramble {idx}: order expected {_EXPECTED[idx]['order']}, got {n}"

    @pytest.mark.parametrize("idx", range(5))
    def test_order_yields_identity(self, idx):
        """Verify that applying the scramble n times actually gives identity."""
        agent = _load_agent_results()
        n = int(agent[idx]["order"])
        assert 1 <= n <= 1260, \
            f"Scramble {idx}: order {n} outside valid range [1, 1260]"
        with open("/app/scrambles.txt") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        s = _parse_scramble(lines[idx])
        state = _make_identity()
        for _ in range(n):
            state = _compose(state, s)
        assert state == _make_identity(), \
            f"Scramble {idx}: state^{n} is not identity"

    @pytest.mark.parametrize("idx", range(5))
    def test_order_is_minimal(self, idx):
        """Verify no proper divisor of n also yields identity."""
        agent = _load_agent_results()
        n = int(agent[idx]["order"])
        if n == 1:
            return  # trivially minimal
        with open("/app/scrambles.txt") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        s = _parse_scramble(lines[idx])
        # Factor n to find prime divisors
        temp = n
        primes = set()
        d = 2
        while d * d <= temp:
            while temp % d == 0:
                primes.add(d)
                temp //= d
            d += 1
        if temp > 1:
            primes.add(temp)
        # For each prime factor p, verify state^(n/p) != identity
        for p in primes:
            k = n // p
            state = _make_identity()
            for _ in range(k):
                state = _compose(state, s)
            assert state != _make_identity(), \
                f"Scramble {idx}: order {n} not minimal, {k} also yields identity"
