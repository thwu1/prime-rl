
"""
Verification tests for the 15-puzzle optimal solver.
Checks move-sequence validity, goal reachability, and optimal solution lengths.
"""

import json
import pytest

W = 4
GOAL = list(range(16))  # [0, 1, 2, ..., 15]

# Puzzle instances from /app/puzzles.txt (Korf 100 subset)
PUZZLES = {
    "1":  [14, 13, 15,  7, 11, 12,  9,  5,  6,  0,  2,  1,  4,  8, 10,  3],
    "2":  [13,  5,  4, 10,  9, 12,  8, 14,  2,  3,  7,  1,  0, 15, 11,  6],
    "3":  [14,  7,  8,  2, 13, 11, 10,  4,  9, 12,  5,  0,  3,  6,  1, 15],
    "4":  [ 5, 12, 10,  7, 15, 11, 14,  0,  8,  2,  1, 13,  3,  4,  9,  6],
    "6":  [14,  7,  1,  9, 12,  3,  6, 15,  8, 11,  2,  5, 10,  0,  4, 13],
    "7":  [ 2, 11, 15,  5, 13,  4,  6,  7, 12,  8, 10,  1,  9,  3, 14,  0],
    "9":  [ 3, 14,  9, 11,  5,  4,  8,  2, 13, 12,  6,  7, 10,  1, 15,  0],
    "10": [13, 11,  8,  9,  0, 15,  7, 10,  4,  3,  6, 14,  5, 12,  2,  1],
}

# Known optimal solution lengths (Korf, AIJ 1985; independently verified)
OPTIMAL = {
    "1": 57,
    "2": 55,
    "3": 59,
    "4": 56,
    "6": 52,
    "7": 52,
    "9": 46,
    "10": 59,
}

INSTANCE_IDS = list(OPTIMAL.keys())


def simulate_moves(initial, moves):
    """Simulate a move sequence on the 15-puzzle. Returns final state."""
    state = list(initial)
    blank = state.index(0)
    for i, move in enumerate(moves):
        r, c = blank // W, blank % W
        if move == "U":
            assert r > 0, f"Move {i}: U invalid at row 0"
            nb = blank - W
        elif move == "D":
            assert r < W - 1, f"Move {i}: D invalid at row {W-1}"
            nb = blank + W
        elif move == "L":
            assert c > 0, f"Move {i}: L invalid at col 0"
            nb = blank - 1
        elif move == "R":
            assert c < W - 1, f"Move {i}: R invalid at col {W-1}"
            nb = blank + 1
        else:
            raise ValueError(f"Move {i}: invalid character '{move}'")
        state[blank], state[nb] = state[nb], state[blank]
        blank = nb
    return state


def manhattan_distance(state):
    """Manhattan distance lower bound for the 15-puzzle."""
    md = 0
    for pos, tile in enumerate(state):
        if tile == 0:
            continue
        gr, gc = tile // W, tile % W
        cr, cc = pos // W, pos % W
        md += abs(gr - cr) + abs(gc - cc)
    return md


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


class TestResultsFormat:
    def test_file_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_all_instances_present(self, results):
        for iid in INSTANCE_IDS:
            assert iid in results, f"Instance {iid} missing from results"

    @pytest.mark.parametrize("iid", INSTANCE_IDS)
    def test_fields_present(self, results, iid):
        entry = results[iid]
        assert "length" in entry, f"Instance {iid}: missing 'length'"
        assert "moves" in entry, f"Instance {iid}: missing 'moves'"

    @pytest.mark.parametrize("iid", INSTANCE_IDS)
    def test_moves_chars_valid(self, results, iid):
        moves = results[iid]["moves"]
        assert all(
            c in "UDLR" for c in moves
        ), f"Instance {iid}: moves contain invalid characters"

    @pytest.mark.parametrize("iid", INSTANCE_IDS)
    def test_length_matches_moves(self, results, iid):
        entry = results[iid]
        assert entry["length"] == len(
            entry["moves"]
        ), f"Instance {iid}: length {entry['length']} != len(moves) {len(entry['moves'])}"


class TestSolutionCorrectness:
    @pytest.mark.parametrize("iid", INSTANCE_IDS)
    def test_reaches_goal(self, results, iid):
        """Simulate the move sequence and verify it reaches the goal state."""
        moves = results[iid]["moves"]
        final = simulate_moves(PUZZLES[iid], moves)
        assert final == GOAL, f"Instance {iid}: solution does not reach goal state"

    @pytest.mark.parametrize("iid", INSTANCE_IDS)
    def test_lower_bound(self, results, iid):
        """Solution length must be >= Manhattan distance."""
        length = results[iid]["length"]
        md = manhattan_distance(PUZZLES[iid])
        assert length >= md, f"Instance {iid}: length {length} < MD {md}"

    @pytest.mark.parametrize("iid", INSTANCE_IDS)
    def test_optimal_length(self, results, iid):
        """Solution length must match known optimal value."""
        length = results[iid]["length"]
        expected = OPTIMAL[iid]
        assert (
            length == expected
        ), f"Instance {iid}: length {length} != optimal {expected}"
