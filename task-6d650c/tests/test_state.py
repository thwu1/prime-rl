"""
Tests for the 15-puzzle optimal solver.

"""
import json
import os
import pytest

GOAL = list(range(16))

# Known optimal solution lengths for all solvable instances.
# Korf instances: from Korf (AIJ 1985), confirmed by dozens of
# independent implementations worldwide.
# Custom instances: verified via IDA* with Manhattan distance.
SOLVABLE = {
    # Set A (Korf benchmark)
    (14, 13, 15, 7, 11, 12, 9, 5, 6, 0, 2, 1, 4, 8, 10, 3): 57,
    (3, 14, 9, 11, 5, 4, 8, 2, 13, 12, 6, 7, 10, 1, 15, 0): 46,
    (6, 12, 11, 3, 13, 7, 9, 15, 2, 14, 8, 10, 4, 1, 5, 0): 52,
    (9, 8, 0, 2, 15, 1, 4, 14, 3, 10, 7, 5, 11, 13, 6, 12): 54,
    (10, 0, 2, 4, 5, 1, 6, 12, 11, 13, 9, 7, 15, 3, 14, 8): 59,
    (0, 13, 2, 4, 12, 14, 6, 9, 15, 1, 10, 3, 11, 5, 8, 7): 54,
    (0, 1, 9, 7, 11, 13, 5, 3, 14, 12, 4, 2, 8, 6, 10, 15): 42,
    (6, 0, 5, 10, 11, 12, 9, 2, 1, 7, 4, 3, 14, 8, 13, 15): 45,
    # Set B (custom instances)
    (4, 1, 2, 3, 5, 0, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15): 2,
    (4, 1, 2, 3, 5, 9, 6, 7, 8, 10, 0, 11, 12, 13, 14, 15): 4,
    (4, 1, 2, 3, 5, 9, 6, 7, 8, 10, 14, 11, 12, 13, 15, 0): 6,
    (4, 7, 14, 13, 10, 3, 9, 12, 11, 5, 6, 15, 1, 2, 8, 0): 56,
    (1, 3, 2, 5, 10, 9, 15, 6, 8, 14, 13, 11, 12, 4, 7, 0): 42,
}

# Known unsolvable configurations that must NOT appear in results.
UNSOLVABLE_CONFIGS = [
    (2, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 12, 13, 14, 15),
    (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 12, 14, 13, 15),
]

SOLVABLE_ITEMS = list(SOLVABLE.items())


def simulate_moves(start, moves_str):
    """Simulate a move sequence on a 4x4 board. Returns final state."""
    board = list(start)
    blank = board.index(0)
    moves = moves_str.split() if moves_str.strip() else []

    for i, move in enumerate(moves):
        br, bc = blank // 4, blank % 4
        if move == "U":
            nr, nc = br - 1, bc
        elif move == "D":
            nr, nc = br + 1, bc
        elif move == "L":
            nr, nc = br, bc - 1
        elif move == "R":
            nr, nc = br, bc + 1
        else:
            raise ValueError(f"Move {i}: invalid direction '{move}'")

        if not (0 <= nr < 4 and 0 <= nc < 4):
            raise ValueError(
                f"Move {i}: '{move}' out of bounds from ({br},{bc})"
            )

        new_blank = nr * 4 + nc
        board[blank], board[new_blank] = board[new_blank], board[blank]
        blank = new_blank

    return board


def manhattan_distance(state):
    """Compute Manhattan distance heuristic for the 15-puzzle."""
    dist = 0
    for pos, tile in enumerate(state):
        if tile == 0:
            continue
        dist += abs(tile // 4 - pos // 4) + abs(tile % 4 - pos % 4)
    return dist


def ida_star_verify(start, node_limit=2_000_000):
    """IDA* with Manhattan distance for independently verifying easy instances.
    Returns optimal length or None if node limit exceeded."""
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    opp = [1, 0, 3, 2]
    nodes = [0]

    def dfs(board, blank, g, threshold, last_d):
        nodes[0] += 1
        if nodes[0] > node_limit:
            return -2
        h = manhattan_distance(board)
        f = g + h
        if f > threshold:
            return f
        if h == 0:
            return -1
        min_f = 9999
        br, bc = blank // 4, blank % 4
        for d in range(4):
            if last_d >= 0 and d == opp[last_d]:
                continue
            nr, nc = br + dr[d], bc + dc[d]
            if not (0 <= nr < 4 and 0 <= nc < 4):
                continue
            np = nr * 4 + nc
            tile = board[np]
            board[blank] = tile
            board[np] = 0
            r = dfs(board, np, g + 1, threshold, d)
            board[np] = tile
            board[blank] = 0
            if r == -1 or r == -2:
                return r
            if r < min_f:
                min_f = r
        return min_f

    board = list(start)
    blank = board.index(0)
    h = manhattan_distance(board)
    if h == 0:
        return 0
    threshold = h
    while True:
        nodes[0] = 0
        r = dfs(board, blank, 0, threshold, -1)
        if r == -1:
            return threshold
        if r == -2:
            return None
        if r >= 9999:
            return None
        threshold = r


# --- Fixtures ---


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results_by_tiles(results):
    return {tuple(e["tiles"]): e for e in results}


# --- Tests ---


class TestFileStructure:
    def test_results_exist(self):
        assert os.path.isfile("/app/results.json"), \
            "/app/results.json not found"

    def test_valid_json(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        assert isinstance(data, list), "results.json must be a JSON array"

    def test_entry_structure(self, results):
        for i, entry in enumerate(results):
            assert "tiles" in entry, f"Entry {i}: missing 'tiles'"
            assert "length" in entry, f"Entry {i}: missing 'length'"
            assert "moves" in entry, f"Entry {i}: missing 'moves'"
            assert isinstance(entry["tiles"], list), \
                f"Entry {i}: 'tiles' must be a list"
            assert len(entry["tiles"]) == 16, \
                f"Entry {i}: 'tiles' must have 16 elements"
            assert isinstance(entry["length"], int), \
                f"Entry {i}: 'length' must be int"
            assert isinstance(entry["moves"], str), \
                f"Entry {i}: 'moves' must be string"


class TestSolvabilityFiltering:
    def test_correct_count(self, results):
        assert len(results) == len(SOLVABLE), \
            f"Expected {len(SOLVABLE)} solvable results, got {len(results)}"

    def test_no_unsolvable_instances(self, results):
        for entry in results:
            key = tuple(entry["tiles"])
            assert key not in UNSOLVABLE_CONFIGS, \
                f"Unsolvable configuration found in results: {list(key)}"

    def test_all_solvable_present(self, results_by_tiles):
        for tiles_tuple in SOLVABLE:
            assert tiles_tuple in results_by_tiles, \
                f"Missing solvable instance: {list(tiles_tuple)[:4]}..."


class TestSolutionValidity:
    """Verify each solution reaches the goal via legal moves."""

    @pytest.mark.parametrize(
        "idx", range(len(SOLVABLE_ITEMS)),
        ids=[f"inst{i}_opt{v}" for i, (_, v) in enumerate(SOLVABLE_ITEMS)]
    )
    def test_valid_path(self, idx, results_by_tiles):
        tiles_tuple, expected_len = SOLVABLE_ITEMS[idx]
        entry = results_by_tiles.get(tiles_tuple)
        if entry is None:
            pytest.fail(f"Instance {list(tiles_tuple)[:4]}... not in results")

        length = entry["length"]
        moves = entry["moves"]
        move_list = moves.split() if moves.strip() else []

        assert len(move_list) == length, \
            f"Declared {length} moves but {len(move_list)} given"

        final = simulate_moves(list(tiles_tuple), moves)
        assert final == GOAL, \
            f"Solution does not reach goal state"


class TestOptimality:
    """Verify solution lengths match known optima."""

    @pytest.mark.parametrize(
        "idx", range(len(SOLVABLE_ITEMS)),
        ids=[f"inst{i}_opt{v}" for i, (_, v) in enumerate(SOLVABLE_ITEMS)]
    )
    def test_optimal_length(self, idx, results_by_tiles):
        tiles_tuple, expected_len = SOLVABLE_ITEMS[idx]
        entry = results_by_tiles.get(tiles_tuple)
        if entry is None:
            pytest.fail(f"Instance not in results")

        assert entry["length"] == expected_len, \
            f"Expected optimal {expected_len}, got {entry['length']}"

    @pytest.mark.parametrize(
        "idx", range(len(SOLVABLE_ITEMS)),
        ids=[f"inst{i}_md" for i in range(len(SOLVABLE_ITEMS))]
    )
    def test_manhattan_lower_bound(self, idx, results_by_tiles):
        tiles_tuple, _ = SOLVABLE_ITEMS[idx]
        entry = results_by_tiles.get(tiles_tuple)
        if entry is None:
            pytest.skip("Instance not in results")

        md = manhattan_distance(list(tiles_tuple))
        assert entry["length"] >= md, \
            f"Solution {entry['length']} < Manhattan distance {md}"


class TestEasyVerification:
    """Independent verification of easy instances via Python IDA*."""

    @pytest.mark.parametrize(
        "tiles_tuple,expected_len",
        [
            ((4, 1, 2, 3, 5, 0, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15), 2),
            ((4, 1, 2, 3, 5, 9, 6, 7, 8, 10, 0, 11, 12, 13, 14, 15), 4),
            ((4, 1, 2, 3, 5, 9, 6, 7, 8, 10, 14, 11, 12, 13, 15, 0), 6),
        ],
        ids=["easy_2", "easy_4", "easy_6"],
    )
    def test_ida_star_crosscheck(self, tiles_tuple, expected_len, results_by_tiles):
        opt = ida_star_verify(list(tiles_tuple))
        assert opt is not None, "IDA* verification timed out"

        entry = results_by_tiles.get(tiles_tuple)
        if entry is None:
            pytest.fail("Instance not in results")

        assert entry["length"] == opt, \
            f"IDA* found optimal {opt}, solver gave {entry['length']}"
