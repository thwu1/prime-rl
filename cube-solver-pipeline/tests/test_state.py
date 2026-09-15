"""Tests for Rubik's Cube group-theoretic analysis.

"""

import json
import os
import csv
from math import gcd
from collections import Counter

import pytest


SOLVED = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

# ── Reference cube simulator ────────────────────────────────────────────────

MOVES = {
    "U": [(0,2,8,6),(1,5,7,3),(9,18,36,45),(10,19,37,46),(11,20,38,47)],
    "R": [(9,11,17,15),(10,14,16,12),(8,45,35,26),(20,2,51,29),(5,48,32,23)],
    "F": [(18,20,26,24),(19,23,25,21),(6,9,29,44),(38,8,15,27),(7,12,28,41)],
    "D": [(27,29,35,33),(28,32,34,30),(24,15,51,42),(26,17,53,44),(25,16,52,43)],
    "L": [(36,38,44,42),(37,41,43,39),(0,18,27,53),(47,6,24,33),(3,21,30,50)],
    "B": [(45,47,53,51),(46,50,52,48),(2,36,33,17),(11,0,42,35),(1,39,34,14)],
}


def _apply_cycles(state, cycles):
    new = list(state)
    for cycle in cycles:
        temp = new[cycle[-1]]
        for i in range(len(cycle) - 1, 0, -1):
            new[cycle[i]] = new[cycle[i - 1]]
        new[cycle[0]] = temp
    return "".join(new)


def _apply_move(state, face):
    return _apply_cycles(state, MOVES[face])


def _apply_move_sequence(state, sequence_str):
    for token in sequence_str.strip().split():
        face = token[0]
        if len(token) == 1:
            state = _apply_move(state, face)
        elif token[1] == "'":
            for _ in range(3):
                state = _apply_move(state, face)
        elif token[1] == "2":
            for _ in range(2):
                state = _apply_move(state, face)
    return state


# ── Cubie conventions (Kociemba standard) ───────────────────────────────────

CORNER_FACELETS = [
    (8, 9, 20),    # URF=0
    (6, 18, 38),   # UFL=1
    (0, 36, 47),   # ULB=2
    (2, 45, 11),   # UBR=3
    (29, 26, 15),  # DFR=4
    (27, 44, 24),  # DLF=5
    (33, 53, 42),  # DBL=6
    (35, 17, 51),  # DRB=7
]

CORNER_COLORS = [
    ('U', 'R', 'F'), ('U', 'F', 'L'), ('U', 'L', 'B'), ('U', 'B', 'R'),
    ('D', 'F', 'R'), ('D', 'L', 'F'), ('D', 'B', 'L'), ('D', 'R', 'B'),
]

EDGE_FACELETS = [
    (5, 10),   # UR=0
    (7, 19),   # UF=1
    (3, 37),   # UL=2
    (1, 46),   # UB=3
    (32, 16),  # DR=4
    (28, 25),  # DF=5
    (30, 43),  # DL=6
    (34, 52),  # DB=7
    (23, 12),  # FR=8
    (21, 41),  # FL=9
    (50, 39),  # BL=10
    (48, 14),  # BR=11
]

EDGE_COLORS = [
    ('U', 'R'), ('U', 'F'), ('U', 'L'), ('U', 'B'),
    ('D', 'R'), ('D', 'F'), ('D', 'L'), ('D', 'B'),
    ('F', 'R'), ('F', 'L'), ('B', 'L'), ('B', 'R'),
]


def _get_corner_cubie(state, pos):
    """Return (cubie_id, orientation) for corner at position pos."""
    f = CORNER_FACELETS[pos]
    colors = tuple(state[i] for i in f)
    color_set = set(colors)
    for cid, cc in enumerate(CORNER_COLORS):
        if set(cc) == color_set:
            ref_color = cc[0]  # always U or D
            for ori in range(3):
                if colors[ori] == ref_color:
                    return cid, ori
    raise ValueError(f"Invalid corner at position {pos}: {colors}")


def _get_edge_cubie(state, pos):
    """Return (cubie_id, orientation) for edge at position pos."""
    f = EDGE_FACELETS[pos]
    colors = tuple(state[i] for i in f)
    color_set = set(colors)
    for eid, ec in enumerate(EDGE_COLORS):
        if set(ec) == color_set:
            ref_color = ec[0]
            if colors[0] == ref_color:
                return eid, 0
            else:
                return eid, 1
    raise ValueError(f"Invalid edge at position {pos}: {colors}")


def _full_cubie_analysis(state):
    """Decompose a facelet string into cubie-level coordinates."""
    cp, co, ep, eo = [], [], [], []
    for i in range(8):
        cid, ori = _get_corner_cubie(state, i)
        cp.append(cid)
        co.append(ori)
    for i in range(12):
        eid, ori = _get_edge_cubie(state, i)
        ep.append(eid)
        eo.append(ori)
    return cp, co, ep, eo


def _perm_parity(perm):
    """Compute parity of a permutation. 0 = even, 1 = odd."""
    n = len(perm)
    visited = [False] * n
    parity = 0
    for i in range(n):
        if not visited[i]:
            j = i
            cycle_len = 0
            while not visited[j]:
                visited[j] = True
                j = perm[j]
                cycle_len += 1
            if cycle_len > 1:
                parity ^= (cycle_len + 1) % 2
    return parity


def _get_cycles(perm):
    """Return list of cycles (as lists of positions) in the permutation."""
    n = len(perm)
    visited = [False] * n
    cycles = []
    for i in range(n):
        if not visited[i]:
            cycle = []
            j = i
            while not visited[j]:
                visited[j] = True
                cycle.append(j)
                j = perm[j]
            cycles.append(cycle)
    return cycles


def _lcm(a, b):
    return a * b // gcd(a, b)


def _compute_algebraic_order(cp, co, ep, eo):
    """Compute the order of the cube state using wreath product cycle analysis."""
    order = 1

    # Corner cycles with augmented orders
    for cycle in _get_cycles(cp):
        k = len(cycle)
        twist_sum = sum(co[j] for j in cycle)
        aug = k if twist_sum % 3 == 0 else 3 * k
        order = _lcm(order, aug)

    # Edge cycles with augmented orders
    for cycle in _get_cycles(ep):
        k = len(cycle)
        flip_sum = sum(eo[j] for j in cycle)
        aug = k if flip_sum % 2 == 0 else 2 * k
        order = _lcm(order, aug)

    return order


def _compute_brute_force_order(scramble):
    """Compute order by brute-force iteration. Max order in cube group is 1260."""
    state = SOLVED
    for i in range(1, 1500):
        state = _apply_move_sequence(state, scramble)
        if state == SOLVED:
            return i
    raise ValueError(f"Order exceeds 1500 for scramble: {scramble}")


def _compute_solvability(state):
    """Analyze solvability invariants of a cube state."""
    cp, co, ep, eo = _full_cubie_analysis(state)
    cts = sum(co) % 3
    efs = sum(eo) % 2
    c_par = _perm_parity(cp)
    e_par = _perm_parity(ep)

    violations = []
    if cts != 0:
        violations.append("corner_twist")
    if efs != 0:
        violations.append("edge_flip")
    if c_par != e_par:
        violations.append("parity_mismatch")

    return {
        "corner_twist_sum_mod3": cts,
        "edge_flip_sum_mod2": efs,
        "corner_parity": c_par,
        "edge_parity": e_par,
        "violations": violations,
        "solvable": len(violations) == 0,
    }


def _compute_expected_statistics():
    """Independently compute statistics from raw TSV."""
    results = []
    with open("/app/fmc_results.tsv", "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(row)

    sub20 = set()
    for r in results:
        best = int(r["best"])
        if 0 < best <= 20:
            sub20.add(r["person_id"])

    comp_pids = {}
    for r in results:
        comp = r["competition_id"]
        pid = r["person_id"]
        if comp not in comp_pids:
            comp_pids[comp] = set()
        comp_pids[comp].add(pid)
    largest = max(comp_pids.items(), key=lambda x: len(x[1]))

    person_counts = Counter()
    for r in results:
        if int(r["best"]) > 0:
            person_counts[r["person_id"]] += 1
    top_person = person_counts.most_common(1)[0]

    return {
        "sub20_count": len(sub20),
        "largest_competition": largest[0],
        "most_results_person": top_person[0],
    }


# ── Precompute expected values ──────────────────────────────────────────────

SCRAMBLES = json.load(open("/app/scrambles.json"))
VALID_STATES = [_apply_move_sequence(SOLVED, s) for s in SCRAMBLES]
INVALID_STATES = json.load(open("/app/invalid_states.json"))

EXPECTED_CUBIE = []
for vs in VALID_STATES:
    cp, co, ep, eo = _full_cubie_analysis(vs)
    EXPECTED_CUBIE.append({"cp": cp, "co": co, "ep": ep, "eo": eo})

EXPECTED_ORDERS = [_compute_brute_force_order(s) for s in SCRAMBLES]

EXPECTED_SOLVABILITY = [_compute_solvability(inv) for inv in INVALID_STATES]


# ── Tests ───────────────────────────────────────────────────────────────────

class TestOutputFilesExist:
    def test_cubie_decomposition_exists(self):
        assert os.path.isfile("/app/output/cubie_decomposition.json"), \
            "Missing /app/output/cubie_decomposition.json"

    def test_algebraic_orders_exists(self):
        assert os.path.isfile("/app/output/algebraic_orders.json"), \
            "Missing /app/output/algebraic_orders.json"

    def test_solvability_analysis_exists(self):
        assert os.path.isfile("/app/output/solvability_analysis.json"), \
            "Missing /app/output/solvability_analysis.json"

    def test_solutions_exists(self):
        assert os.path.isfile("/app/output/solutions.json"), \
            "Missing /app/output/solutions.json"

    def test_statistics_exists(self):
        assert os.path.isfile("/app/output/statistics.json"), \
            "Missing /app/output/statistics.json"


class TestCubieDecomposition:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/cubie_decomposition.json") as f:
            self.data = json.load(f)

    def test_correct_count(self):
        assert len(self.data) == 5, f"Expected 5 entries, got {len(self.data)}"

    def test_has_required_keys(self):
        for i, d in enumerate(self.data):
            for key in ["corner_permutation", "corner_orientation",
                        "edge_permutation", "edge_orientation"]:
                assert key in d, f"Entry {i} missing key '{key}'"

    def test_corner_permutation_valid(self):
        for i, d in enumerate(self.data):
            cp = d["corner_permutation"]
            assert len(cp) == 8, f"Entry {i}: corner_permutation has {len(cp)} elements"
            assert sorted(cp) == list(range(8)), \
                f"Entry {i}: corner_permutation is not a valid permutation of 0-7"

    def test_corner_orientation_valid(self):
        for i, d in enumerate(self.data):
            co = d["corner_orientation"]
            assert len(co) == 8, f"Entry {i}: corner_orientation has {len(co)} elements"
            for j, v in enumerate(co):
                assert v in (0, 1, 2), \
                    f"Entry {i}: corner_orientation[{j}] = {v}, expected 0, 1, or 2"

    def test_edge_permutation_valid(self):
        for i, d in enumerate(self.data):
            ep = d["edge_permutation"]
            assert len(ep) == 12, f"Entry {i}: edge_permutation has {len(ep)} elements"
            assert sorted(ep) == list(range(12)), \
                f"Entry {i}: edge_permutation is not a valid permutation of 0-11"

    def test_edge_orientation_valid(self):
        for i, d in enumerate(self.data):
            eo = d["edge_orientation"]
            assert len(eo) == 12, f"Entry {i}: edge_orientation has {len(eo)} elements"
            for j, v in enumerate(eo):
                assert v in (0, 1), \
                    f"Entry {i}: edge_orientation[{j}] = {v}, expected 0 or 1"

    def test_corner_twist_sum_invariant(self):
        """For valid cube states, corner twist sum must be 0 mod 3."""
        for i, d in enumerate(self.data):
            co = d["corner_orientation"]
            assert sum(co) % 3 == 0, \
                f"Entry {i}: corner twist sum = {sum(co)}, not 0 mod 3"

    def test_edge_flip_sum_invariant(self):
        """For valid cube states, edge flip sum must be 0 mod 2."""
        for i, d in enumerate(self.data):
            eo = d["edge_orientation"]
            assert sum(eo) % 2 == 0, \
                f"Entry {i}: edge flip sum = {sum(eo)}, not 0 mod 2"

    def test_parity_invariant(self):
        """Corner and edge permutation parities must match."""
        for i, d in enumerate(self.data):
            c_par = _perm_parity(d["corner_permutation"])
            e_par = _perm_parity(d["edge_permutation"])
            assert c_par == e_par, \
                f"Entry {i}: corner parity={c_par}, edge parity={e_par} (must match)"

    def test_corner_permutation_matches(self):
        for i, d in enumerate(self.data):
            assert d["corner_permutation"] == EXPECTED_CUBIE[i]["cp"], \
                f"Entry {i}: corner_permutation mismatch.\n" \
                f"  Got:      {d['corner_permutation']}\n" \
                f"  Expected: {EXPECTED_CUBIE[i]['cp']}"

    def test_corner_orientation_matches(self):
        for i, d in enumerate(self.data):
            assert d["corner_orientation"] == EXPECTED_CUBIE[i]["co"], \
                f"Entry {i}: corner_orientation mismatch.\n" \
                f"  Got:      {d['corner_orientation']}\n" \
                f"  Expected: {EXPECTED_CUBIE[i]['co']}"

    def test_edge_permutation_matches(self):
        for i, d in enumerate(self.data):
            assert d["edge_permutation"] == EXPECTED_CUBIE[i]["ep"], \
                f"Entry {i}: edge_permutation mismatch.\n" \
                f"  Got:      {d['edge_permutation']}\n" \
                f"  Expected: {EXPECTED_CUBIE[i]['ep']}"

    def test_edge_orientation_matches(self):
        for i, d in enumerate(self.data):
            assert d["edge_orientation"] == EXPECTED_CUBIE[i]["eo"], \
                f"Entry {i}: edge_orientation mismatch.\n" \
                f"  Got:      {d['edge_orientation']}\n" \
                f"  Expected: {EXPECTED_CUBIE[i]['eo']}"


class TestAlgebraicOrders:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/algebraic_orders.json") as f:
            self.data = json.load(f)

    def test_correct_count(self):
        assert len(self.data) == 5

    def test_has_required_keys(self):
        for i, d in enumerate(self.data):
            for key in ["corner_cycle_type", "edge_cycle_type",
                        "augmented_corner_orders", "augmented_edge_orders",
                        "permutation_order"]:
                assert key in d, f"Entry {i} missing key '{key}'"

    def test_cycle_types_sorted(self):
        for i, d in enumerate(self.data):
            assert d["corner_cycle_type"] == sorted(d["corner_cycle_type"]), \
                f"Entry {i}: corner_cycle_type not sorted"
            assert d["edge_cycle_type"] == sorted(d["edge_cycle_type"]), \
                f"Entry {i}: edge_cycle_type not sorted"

    def test_corner_cycle_type_sums(self):
        """Sum of corner cycle lengths must be 8."""
        for i, d in enumerate(self.data):
            assert sum(d["corner_cycle_type"]) == 8, \
                f"Entry {i}: corner cycle lengths sum to {sum(d['corner_cycle_type'])}, expected 8"

    def test_edge_cycle_type_sums(self):
        """Sum of edge cycle lengths must be 12."""
        for i, d in enumerate(self.data):
            assert sum(d["edge_cycle_type"]) == 12, \
                f"Entry {i}: edge cycle lengths sum to {sum(d['edge_cycle_type'])}, expected 12"

    def test_corner_cycle_type_matches(self):
        for i, d in enumerate(self.data):
            exp = EXPECTED_CUBIE[i]
            expected_type = sorted(len(c) for c in _get_cycles(exp["cp"]))
            assert d["corner_cycle_type"] == expected_type, \
                f"Entry {i}: corner_cycle_type mismatch. Got {d['corner_cycle_type']}, expected {expected_type}"

    def test_edge_cycle_type_matches(self):
        for i, d in enumerate(self.data):
            exp = EXPECTED_CUBIE[i]
            expected_type = sorted(len(c) for c in _get_cycles(exp["ep"]))
            assert d["edge_cycle_type"] == expected_type, \
                f"Entry {i}: edge_cycle_type mismatch. Got {d['edge_cycle_type']}, expected {expected_type}"

    def test_permutation_order_positive(self):
        for i, d in enumerate(self.data):
            assert isinstance(d["permutation_order"], int) and d["permutation_order"] > 0

    def test_permutation_order_within_group_bound(self):
        """Max order in the Rubik's Cube group is 1260."""
        for i, d in enumerate(self.data):
            assert d["permutation_order"] <= 1260, \
                f"Entry {i}: order {d['permutation_order']} exceeds max group order 1260"

    def test_permutation_order_matches_brute_force(self):
        """The algebraically computed order must match brute-force verification."""
        for i, d in enumerate(self.data):
            assert d["permutation_order"] == EXPECTED_ORDERS[i], \
                f"Entry {i}: permutation_order={d['permutation_order']}, " \
                f"brute_force={EXPECTED_ORDERS[i]}"

    def test_permutation_order_matches_algebraic(self):
        """Verify using our own algebraic computation."""
        for i, d in enumerate(self.data):
            exp = EXPECTED_CUBIE[i]
            alg_order = _compute_algebraic_order(
                exp["cp"], exp["co"], exp["ep"], exp["eo"])
            assert d["permutation_order"] == alg_order, \
                f"Entry {i}: permutation_order={d['permutation_order']}, " \
                f"algebraic={alg_order}"

    def test_augmented_orders_consistent_with_lcm(self):
        """The permutation_order must be the LCM of all augmented orders."""
        for i, d in enumerate(self.data):
            all_augs = d["augmented_corner_orders"] + d["augmented_edge_orders"]
            computed_lcm = 1
            for a in all_augs:
                computed_lcm = _lcm(computed_lcm, a)
            assert d["permutation_order"] == computed_lcm, \
                f"Entry {i}: LCM of augmented orders = {computed_lcm}, " \
                f"but permutation_order = {d['permutation_order']}"


class TestSolvabilityAnalysis:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/solvability_analysis.json") as f:
            self.data = json.load(f)

    def test_correct_count(self):
        assert len(self.data) == 5

    def test_has_required_keys(self):
        for i, d in enumerate(self.data):
            for key in ["corner_twist_sum_mod3", "edge_flip_sum_mod2",
                        "corner_parity", "edge_parity", "violations", "solvable"]:
                assert key in d, f"Entry {i} missing key '{key}'"

    def test_corner_twist_sum_matches(self):
        for i, d in enumerate(self.data):
            assert d["corner_twist_sum_mod3"] == EXPECTED_SOLVABILITY[i]["corner_twist_sum_mod3"], \
                f"Entry {i}: corner_twist_sum_mod3={d['corner_twist_sum_mod3']}, " \
                f"expected {EXPECTED_SOLVABILITY[i]['corner_twist_sum_mod3']}"

    def test_edge_flip_sum_matches(self):
        for i, d in enumerate(self.data):
            assert d["edge_flip_sum_mod2"] == EXPECTED_SOLVABILITY[i]["edge_flip_sum_mod2"], \
                f"Entry {i}: edge_flip_sum_mod2={d['edge_flip_sum_mod2']}, " \
                f"expected {EXPECTED_SOLVABILITY[i]['edge_flip_sum_mod2']}"

    def test_corner_parity_matches(self):
        for i, d in enumerate(self.data):
            assert d["corner_parity"] == EXPECTED_SOLVABILITY[i]["corner_parity"], \
                f"Entry {i}: corner_parity={d['corner_parity']}, " \
                f"expected {EXPECTED_SOLVABILITY[i]['corner_parity']}"

    def test_edge_parity_matches(self):
        for i, d in enumerate(self.data):
            assert d["edge_parity"] == EXPECTED_SOLVABILITY[i]["edge_parity"], \
                f"Entry {i}: edge_parity={d['edge_parity']}, " \
                f"expected {EXPECTED_SOLVABILITY[i]['edge_parity']}"

    def test_violations_match(self):
        for i, d in enumerate(self.data):
            assert sorted(d["violations"]) == sorted(EXPECTED_SOLVABILITY[i]["violations"]), \
                f"Entry {i}: violations={d['violations']}, " \
                f"expected {EXPECTED_SOLVABILITY[i]['violations']}"

    def test_solvable_matches(self):
        for i, d in enumerate(self.data):
            assert d["solvable"] == EXPECTED_SOLVABILITY[i]["solvable"], \
                f"Entry {i}: solvable={d['solvable']}, " \
                f"expected {EXPECTED_SOLVABILITY[i]['solvable']}"

    def test_no_valid_states_are_solvable(self):
        """All 5 invalid states must be unsolvable."""
        for i, d in enumerate(self.data):
            assert d["solvable"] is False, \
                f"Entry {i}: expected unsolvable, but solvable=True"

    def test_violations_not_empty(self):
        """Each invalid state must have at least one violation."""
        for i, d in enumerate(self.data):
            assert len(d["violations"]) > 0, \
                f"Entry {i}: no violations found in invalid state"

    def test_violations_are_valid_strings(self):
        valid = {"corner_twist", "edge_flip", "parity_mismatch"}
        for i, d in enumerate(self.data):
            for v in d["violations"]:
                assert v in valid, \
                    f"Entry {i}: invalid violation string '{v}'"


class TestSolutions:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/solutions.json") as f:
            self.solutions = json.load(f)

    def test_correct_count(self):
        assert len(self.solutions) == 5

    def test_has_required_keys(self):
        for i, sol in enumerate(self.solutions):
            assert "solution" in sol, f"Solution {i} missing 'solution' key"
            assert "move_count" in sol, f"Solution {i} missing 'move_count' key"
            assert "verified" in sol, f"Solution {i} missing 'verified' key"

    def test_move_count_matches(self):
        for i, sol in enumerate(self.solutions):
            actual_count = len(sol["solution"].strip().split())
            assert sol["move_count"] == actual_count, \
                f"Solution {i}: move_count={sol['move_count']} but " \
                f"solution has {actual_count} moves"

    def test_move_count_reasonable(self):
        for i, sol in enumerate(self.solutions):
            assert sol["move_count"] <= 25, \
                f"Solution {i} has {sol['move_count']} moves, expected <= 25"

    def test_solutions_verified(self):
        for i, sol in enumerate(self.solutions):
            assert sol["verified"] is True, f"Solution {i} not verified"

    def test_solutions_actually_solve(self):
        """Independently verify each solution restores the solved state."""
        for i, sol in enumerate(self.solutions):
            scrambled = VALID_STATES[i]
            result = _apply_move_sequence(scrambled, sol["solution"])
            assert result == SOLVED, \
                f"Solution {i} does not produce solved state.\n" \
                f"  Scrambled: {scrambled}\n" \
                f"  Solution:  {sol['solution']}\n" \
                f"  Result:    {result}"


class TestStatistics:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/statistics.json") as f:
            self.stats = json.load(f)
        self.expected = _compute_expected_statistics()

    def test_has_required_keys(self):
        for key in ["sub20_count", "largest_competition", "most_results_person"]:
            assert key in self.stats, f"Missing key '{key}' in statistics.json"

    def test_sub20_count(self):
        assert self.stats["sub20_count"] == self.expected["sub20_count"], \
            f"sub20_count: got {self.stats['sub20_count']}, " \
            f"expected {self.expected['sub20_count']}"

    def test_largest_competition(self):
        assert self.stats["largest_competition"] == self.expected["largest_competition"], \
            f"largest_competition: got {self.stats['largest_competition']}, " \
            f"expected {self.expected['largest_competition']}"

    def test_most_results_person(self):
        assert self.stats["most_results_person"] == self.expected["most_results_person"], \
            f"most_results_person: got {self.stats['most_results_person']}, " \
            f"expected {self.expected['most_results_person']}"
