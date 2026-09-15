"""
Independent verification of Rubik's Cube State Database Audit results.
Implements full cubie-level algebra from first principles, predicts the
buggy validation service's responses, and verifies every field of the
agent's report.json against independently computed answers.
"""

import json
import sqlite3
import pytest

# ---- Constants ----

URF, UFL, ULB, UBR, DFR, DLF, DBL, DRB = range(8)
UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR = range(12)
CU, CR, CF, CD, CL, CB = range(6)

CORNER_FACELET = [
    [8, 9, 20],    # URF: U9, R1, F3
    [6, 18, 38],   # UFL: U7, F1, L3
    [0, 36, 47],   # ULB: U1, L1, B3
    [2, 45, 11],   # UBR: U3, B1, R3
    [29, 26, 15],  # DFR: D3, F9, R7
    [27, 44, 24],  # DLF: D1, L9, F7
    [33, 53, 42],  # DBL: D7, B9, L7
    [35, 17, 51],  # DRB: D9, R9, B7
]

CORNER_COLOR = [
    [CU, CR, CF], [CU, CF, CL], [CU, CL, CB], [CU, CB, CR],
    [CD, CF, CR], [CD, CL, CF], [CD, CB, CL], [CD, CR, CB],
]

EDGE_FACELET = [
    [5, 10],   [7, 19],   [3, 37],   [1, 46],
    [32, 16],  [28, 25],  [30, 43],  [34, 52],
    [23, 12],  [21, 41],  [50, 39],  [48, 14],
]

EDGE_COLOR = [
    [CU, CR], [CU, CF], [CU, CL], [CU, CB],
    [CD, CR], [CD, CF], [CD, CL], [CD, CB],
    [CF, CR], [CF, CL], [CB, CL], [CB, CR],
]

MOVE_DEFS = {
    'U': (
        [UBR, URF, UFL, ULB, DFR, DLF, DBL, DRB],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [UB, UR, UF, UL, DR, DF, DL, DB, FR, FL, BL, BR],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    'R': (
        [DFR, UFL, ULB, URF, DRB, DLF, DBL, UBR],
        [2, 0, 0, 1, 1, 0, 0, 2],
        [FR, UF, UL, UB, BR, DF, DL, DB, DR, FL, BL, UR],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    'F': (
        [UFL, DLF, ULB, UBR, URF, DFR, DBL, DRB],
        [1, 2, 0, 0, 2, 1, 0, 0],
        [UR, FL, UL, UB, DR, FR, DL, DB, UF, DF, BL, BR],
        [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0],
    ),
    'D': (
        [URF, UFL, ULB, UBR, DLF, DBL, DRB, DFR],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [UR, UF, UL, UB, DF, DL, DB, DR, FR, FL, BL, BR],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    'L': (
        [URF, ULB, DBL, UBR, DFR, UFL, DLF, DRB],
        [0, 1, 2, 0, 0, 2, 1, 0],
        [UR, UF, BL, UB, DR, DF, FL, DB, FR, UL, DL, BR],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    ),
    'B': (
        [URF, UFL, UBR, DRB, DFR, DLF, ULB, DBL],
        [0, 0, 1, 2, 0, 0, 2, 1],
        [UR, UF, UL, BR, DR, DF, DL, BL, FR, FL, UB, DB],
        [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1],
    ),
}


class CubieCube:
    def __init__(self, cp=None, co=None, ep=None, eo=None):
        self.cp = list(cp) if cp is not None else list(range(8))
        self.co = list(co) if co is not None else [0] * 8
        self.ep = list(ep) if ep is not None else list(range(12))
        self.eo = list(eo) if eo is not None else [0] * 12

    def copy(self):
        return CubieCube(self.cp, self.co, self.ep, self.eo)

    def is_identity(self):
        return (self.cp == list(range(8)) and self.co == [0] * 8
                and self.ep == list(range(12)) and self.eo == [0] * 12)

    def multiply(self, other):
        new_cp = [self.cp[other.cp[i]] for i in range(8)]
        new_co = [(self.co[other.cp[i]] + other.co[i]) % 3 for i in range(8)]
        new_ep = [self.ep[other.ep[i]] for i in range(12)]
        new_eo = [(self.eo[other.ep[i]] + other.eo[i]) % 2 for i in range(12)]
        self.cp, self.co = new_cp, new_co
        self.ep, self.eo = new_ep, new_eo

    def to_facelet_string(self):
        color_char = 'URFDLB'
        f = [0] * 54
        for i in range(6):
            f[i * 9 + 4] = i
        for i in range(8):
            j = self.cp[i]
            ori = self.co[i]
            for k in range(3):
                f[CORNER_FACELET[i][(k + ori) % 3]] = CORNER_COLOR[j][k]
        for i in range(12):
            j = self.ep[i]
            ori = self.eo[i]
            for k in range(2):
                f[EDGE_FACELET[i][(k + ori) % 2]] = EDGE_COLOR[j][k]
        return ''.join(color_char[c] for c in f)


def make_move(face_char):
    cp, co, ep, eo = MOVE_DEFS[face_char]
    return CubieCube(cp, co, ep, eo)


def parse_and_apply(move_string):
    cc = CubieCube()
    tokens = move_string.split()
    for token in tokens:
        face = token[0]
        if len(token) == 1:
            power = 1
        elif token[1] == "'":
            power = 3
        elif token[1] == '2':
            power = 2
        else:
            power = 1
        basic = make_move(face)
        for _ in range(power):
            cc.multiply(basic)
    return cc


def find_order(cc):
    current = CubieCube()
    for k in range(1, 1261):
        current.multiply(cc)
        if current.is_identity():
            return k
    return -1


def facelet_to_cubie(s):
    color_map = {'U': CU, 'R': CR, 'F': CF, 'D': CD, 'L': CL, 'B': CB}
    f = [color_map[c] for c in s]
    cc = CubieCube()
    cc.cp = [-1] * 8
    cc.ep = [-1] * 12

    for i in range(8):
        fac = CORNER_FACELET[i]
        ori = -1
        for o in range(3):
            if f[fac[o]] == CU or f[fac[o]] == CD:
                ori = o
                break
        if ori == -1:
            return None
        col1 = f[fac[(ori + 1) % 3]]
        col2 = f[fac[(ori + 2) % 3]]
        for j in range(8):
            if col1 == CORNER_COLOR[j][1] and col2 == CORNER_COLOR[j][2]:
                cc.cp[i] = j
                cc.co[i] = ori
                break
        if cc.cp[i] == -1:
            return None

    for i in range(12):
        for j in range(12):
            if (f[EDGE_FACELET[i][0]] == EDGE_COLOR[j][0] and
                    f[EDGE_FACELET[i][1]] == EDGE_COLOR[j][1]):
                cc.ep[i] = j
                cc.eo[i] = 0
                break
            if (f[EDGE_FACELET[i][0]] == EDGE_COLOR[j][1] and
                    f[EDGE_FACELET[i][1]] == EDGE_COLOR[j][0]):
                cc.ep[i] = j
                cc.eo[i] = 1
                break
        if cc.ep[i] == -1:
            return None

    return cc


def validate_state(facelet_str):
    """Return (solvable, violation_type) for a facelet string."""
    for c in 'URFDLB':
        if facelet_str.count(c) != 9:
            return False, "invalid_colors"

    cc = facelet_to_cubie(facelet_str)
    if cc is None:
        return False, "invalid_pieces"
    if sorted(cc.cp) != list(range(8)):
        return False, "invalid_pieces"
    if sorted(cc.ep) != list(range(12)):
        return False, "invalid_pieces"

    # Corner orientation sum mod 3
    if sum(cc.co) % 3 != 0:
        return False, "corner_orientation"

    # Edge orientation sum mod 2
    if sum(cc.eo) % 2 != 0:
        return False, "edge_orientation"

    # Permutation parity check
    c_inv = 0
    for i in range(8):
        for j in range(i + 1, 8):
            if cc.cp[i] > cc.cp[j]:
                c_inv += 1
    e_inv = 0
    for i in range(12):
        for j in range(i + 1, 12):
            if cc.ep[i] > cc.ep[j]:
                e_inv += 1
    if c_inv % 2 != e_inv % 2:
        return False, "permutation_parity"

    return True, None


def service_validate(facelet_str):
    """Predict the buggy validation service's response.

    Matches /app/validator/server.py behavior exactly:
      Bug 1: No permutation parity check.
      Bug 2: All violations reported as 'invalid_state'.
    """
    if len(facelet_str) != 54:
        return {"solvable": False, "violation": "invalid_state"}
    for c in 'URFDLB':
        if facelet_str.count(c) != 9:
            return {"solvable": False, "violation": "invalid_state"}

    cc = facelet_to_cubie(facelet_str)
    if cc is None:
        return {"solvable": False, "violation": "invalid_state"}
    if sorted(cc.cp) != list(range(8)):
        return {"solvable": False, "violation": "invalid_state"}
    if sorted(cc.ep) != list(range(12)):
        return {"solvable": False, "violation": "invalid_state"}

    if sum(cc.co) % 3 != 0:
        return {"solvable": False, "violation": "invalid_state"}
    if sum(cc.eo) % 2 != 0:
        return {"solvable": False, "violation": "invalid_state"}

    # BUG: no permutation parity check (matches server)
    return {"solvable": True, "violation": None}


# ---- Fixtures ----

@pytest.fixture(scope="module")
def puzzle():
    """Load cube data from the SQLite database."""
    conn = sqlite3.connect('/app/cubes.db')
    rows = conn.execute('''
        SELECT f.state_id, f.facelet, g.move_sequence, o.claimed_order
        FROM facelets f
        JOIN generators g ON f.state_id = g.state_id
        JOIN order_claims o ON f.state_id = o.state_id
        ORDER BY f.state_id
    ''').fetchall()
    conn.close()
    states = {}
    for sid, facelet, gen, order in rows:
        states[sid] = {
            'facelet': facelet,
            'claimed_generator': gen,
            'claimed_order': order,
        }
    return {'states': states}


@pytest.fixture(scope="module")
def results():
    with open('/app/report.json') as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def expected_answers(puzzle):
    """Independently compute all expected answers."""
    answers = {}
    for sid, state in puzzle['states'].items():
        fs = state['facelet']
        gen = state['claimed_generator']

        solvable, violation = validate_state(fs)

        if solvable:
            gen_cc = parse_and_apply(gen)
            gen_verified = (gen_cc.to_facelet_string() == fs)
            state_cc = facelet_to_cubie(fs)
            correct_order = find_order(state_cc)
            answers[sid] = {
                "solvable": True,
                "violation": None,
                "generator_verified": gen_verified,
                "correct_order": correct_order,
            }
        else:
            answers[sid] = {
                "solvable": False,
                "violation": violation,
                "generator_verified": None,
                "correct_order": None,
            }

    return answers


@pytest.fixture(scope="module")
def expected_service(puzzle):
    """Predict what the buggy validation service returns for each state."""
    responses = {}
    for sid, state in puzzle['states'].items():
        responses[sid] = service_validate(state['facelet'])
    return responses


STATE_IDS = [f"C{i:02d}" for i in range(1, 13)]


class TestReportStructure:
    def test_all_keys_present(self, results):
        for sid in STATE_IDS:
            assert sid in results, f"Missing state {sid} in report"

    def test_required_fields(self, results):
        required = ["solvable", "violation", "generator_verified",
                     "correct_order", "service_response", "service_agrees"]
        for sid in STATE_IDS:
            entry = results[sid]
            for field in required:
                assert field in entry, f"{sid}: missing '{field}'"

    def test_solvable_is_boolean(self, results):
        for sid in STATE_IDS:
            assert isinstance(results[sid]["solvable"], bool), (
                f"{sid}: 'solvable' must be boolean, got {type(results[sid]['solvable'])}"
            )

    def test_service_agrees_is_boolean(self, results):
        for sid in STATE_IDS:
            assert isinstance(results[sid]["service_agrees"], bool), (
                f"{sid}: 'service_agrees' must be boolean"
            )

    def test_service_response_is_dict(self, results):
        for sid in STATE_IDS:
            sr = results[sid]["service_response"]
            assert isinstance(sr, dict), (
                f"{sid}: 'service_response' must be a dict, got {type(sr)}"
            )
            assert "solvable" in sr, f"{sid}: service_response missing 'solvable'"
            assert "violation" in sr, f"{sid}: service_response missing 'violation'"


class TestSolvability:
    def test_solvable_classification(self, results, expected_answers):
        for sid in STATE_IDS:
            expected = expected_answers[sid]["solvable"]
            actual = results[sid]["solvable"]
            assert actual == expected, (
                f"{sid}: expected solvable={expected}, got {actual}"
            )

    def test_violation_for_unsolvable(self, results, expected_answers):
        for sid in STATE_IDS:
            if not expected_answers[sid]["solvable"]:
                expected_v = expected_answers[sid]["violation"]
                actual_v = results[sid]["violation"]
                assert actual_v == expected_v, (
                    f"{sid}: expected violation='{expected_v}', got '{actual_v}'"
                )

    def test_violation_null_for_solvable(self, results, expected_answers):
        for sid in STATE_IDS:
            if expected_answers[sid]["solvable"]:
                assert results[sid]["violation"] is None, (
                    f"{sid}: solvable state should have violation=null"
                )


class TestGeneratorVerification:
    def test_generator_verified_matches(self, results, expected_answers):
        for sid in STATE_IDS:
            if expected_answers[sid]["solvable"]:
                expected_gv = expected_answers[sid]["generator_verified"]
                actual_gv = results[sid]["generator_verified"]
                assert actual_gv == expected_gv, (
                    f"{sid}: expected generator_verified={expected_gv}, got {actual_gv}"
                )

    def test_generator_null_for_unsolvable(self, results, expected_answers):
        for sid in STATE_IDS:
            if not expected_answers[sid]["solvable"]:
                assert results[sid]["generator_verified"] is None, (
                    f"{sid}: unsolvable state should have generator_verified=null"
                )

    def test_generator_verified_independently(self, results, puzzle):
        """Cross-check: if agent says generator_verified=True, verify independently."""
        for sid in STATE_IDS:
            entry = results[sid]
            if entry["solvable"] and entry["generator_verified"]:
                gen = puzzle['states'][sid]['claimed_generator']
                gen_cc = parse_and_apply(gen)
                actual_fs = puzzle['states'][sid]['facelet']
                assert gen_cc.to_facelet_string() == actual_fs, (
                    f"{sid}: agent claims generator_verified=True but "
                    f"applying generator does not produce the facelet string"
                )


class TestOrder:
    def test_order_matches(self, results, expected_answers):
        for sid in STATE_IDS:
            if expected_answers[sid]["solvable"]:
                expected_o = expected_answers[sid]["correct_order"]
                actual_o = int(results[sid]["correct_order"])
                assert actual_o == expected_o, (
                    f"{sid}: expected order={expected_o}, got {actual_o}"
                )

    def test_order_null_for_unsolvable(self, results, expected_answers):
        for sid in STATE_IDS:
            if not expected_answers[sid]["solvable"]:
                assert results[sid]["correct_order"] is None, (
                    f"{sid}: unsolvable state should have correct_order=null"
                )

    def test_order_produces_identity(self, results, puzzle):
        """Verify that state^order = identity for all solvable states."""
        for sid in STATE_IDS:
            entry = results[sid]
            if entry["solvable"] and entry["correct_order"] is not None:
                o = int(entry["correct_order"])
                assert o > 0, f"{sid}: order must be positive"
                cc = facelet_to_cubie(puzzle['states'][sid]['facelet'])
                result = CubieCube()
                base = cc.copy()
                n = o
                while n > 0:
                    if n % 2 == 1:
                        result.multiply(base)
                    new_base = base.copy()
                    new_base.multiply(base)
                    base = new_base
                    n //= 2
                assert result.is_identity(), (
                    f"{sid}: state^{o} should be identity but is not"
                )

    def test_order_is_minimal(self, results, puzzle):
        """Verify no smaller k yields identity."""
        for sid in STATE_IDS:
            entry = results[sid]
            if entry["solvable"] and entry["correct_order"] is not None:
                o = int(entry["correct_order"])
                if o > 1:
                    cc = facelet_to_cubie(puzzle['states'][sid]['facelet'])
                    result = CubieCube()
                    base = cc.copy()
                    n = o - 1
                    while n > 0:
                        if n % 2 == 1:
                            result.multiply(base)
                        new_base = base.copy()
                        new_base.multiply(base)
                        base = new_base
                        n //= 2
                    assert not result.is_identity(), (
                        f"{sid}: state^{o-1} is identity, so order {o} is not minimal"
                    )


class TestServiceResponse:
    def test_service_solvable_matches(self, results, expected_service):
        """Verify agent correctly reports the service's solvability assessment."""
        for sid in STATE_IDS:
            expected_s = expected_service[sid]["solvable"]
            actual_s = results[sid]["service_response"]["solvable"]
            assert actual_s == expected_s, (
                f"{sid}: expected service solvable={expected_s}, got {actual_s}"
            )

    def test_service_violation_matches(self, results, expected_service):
        """Verify agent correctly reports the service's violation field."""
        for sid in STATE_IDS:
            expected_v = expected_service[sid]["violation"]
            actual_v = results[sid]["service_response"]["violation"]
            assert actual_v == expected_v, (
                f"{sid}: expected service violation='{expected_v}', got '{actual_v}'"
            )

    def test_service_agrees_correct(self, results, expected_answers, expected_service):
        """Verify service_agrees is correctly computed."""
        for sid in STATE_IDS:
            ground_truth = expected_answers[sid]["solvable"]
            service_says = expected_service[sid]["solvable"]
            expected_agrees = (ground_truth == service_says)
            actual_agrees = results[sid]["service_agrees"]
            assert actual_agrees == expected_agrees, (
                f"{sid}: expected service_agrees={expected_agrees}, "
                f"got {actual_agrees} (truth={ground_truth}, "
                f"service={service_says})"
            )

    def test_at_least_one_disagreement(self, expected_answers, expected_service):
        """Sanity: verify the service disagrees on at least one state."""
        disagreements = sum(
            1 for sid in STATE_IDS
            if expected_answers[sid]["solvable"] != expected_service[sid]["solvable"]
        )
        assert disagreements >= 1, (
            "Expected at least one service disagreement but found none"
        )


class TestCrossConsistency:
    def test_solvable_states_have_valid_facelets(self, results, puzzle):
        """All states claimed solvable should independently pass validation."""
        for sid in STATE_IDS:
            if results[sid]["solvable"]:
                fs = puzzle['states'][sid]['facelet']
                valid, vtype = validate_state(fs)
                assert valid, (
                    f"{sid}: agent claims solvable but validation fails with {vtype}"
                )

    def test_unsolvable_states_fail_validation(self, results, puzzle):
        """All states claimed unsolvable should independently fail validation."""
        for sid in STATE_IDS:
            if not results[sid]["solvable"]:
                fs = puzzle['states'][sid]['facelet']
                valid, vtype = validate_state(fs)
                assert not valid, (
                    f"{sid}: agent claims unsolvable but validation passes"
                )

    def test_identity_sanity(self):
        """Verify the test's own reference implementation is correct."""
        identity = CubieCube()
        assert identity.to_facelet_string() == 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'
        assert identity.is_identity()

    def test_basic_move_roundtrip(self):
        """Verify basic move application produces correct facelets."""
        r = make_move('R')
        fs = r.to_facelet_string()
        assert len(fs) == 54
        for c in 'URFDLB':
            assert fs.count(c) == 9

    def test_parity_violated_state_exists(self, puzzle):
        """Verify C07 has a permutation parity violation (sanity check)."""
        fs = puzzle['states']['C07']['facelet']
        solvable, violation = validate_state(fs)
        assert not solvable, "C07 should be unsolvable"
        assert violation == "permutation_parity", (
            f"C07 should have permutation_parity violation, got {violation}"
        )
