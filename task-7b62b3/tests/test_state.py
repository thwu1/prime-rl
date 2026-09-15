
import os
import re
import subprocess
import pytest

PUZZLE = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"

# Known correct solution for the Wikipedia Sudoku puzzle
SUDOKU_ANSWER = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"


def parse_counts(filepath):
    """Parse solution_counts.txt into a dict of {name: count}."""
    counts = {}
    for line in open(filepath):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                name = parts[0].rstrip(":")
                count = int(parts[1])
                counts[name] = count
            except ValueError:
                continue
    return counts


def get_count(counts, name):
    """Look up a count by filename, with or without .dlx suffix."""
    return counts.get(name) or counts.get(name.replace(".dlx", ""))


# ───────── Solution Counts ─────────

class TestSolutionCounts:
    @pytest.fixture(autouse=True)
    def load_counts(self):
        path = "/app/results/solution_counts.txt"
        assert os.path.exists(path), f"{path} does not exist"
        self.counts = parse_counts(path)

    def test_example_count(self):
        c = get_count(self.counts, "example.dlx")
        assert c == 1, f"example.dlx: expected 1, got {c}"

    def test_queens8_count(self):
        c = get_count(self.counts, "queens8.dlx")
        assert c == 92, f"queens8.dlx: expected 92, got {c}"

    def test_rooks6_count(self):
        c = get_count(self.counts, "rooks6.dlx")
        assert c == 720, f"rooks6.dlx: expected 720, got {c}"

    def test_unknown_count(self):
        c = get_count(self.counts, "unknown.dlx")
        assert c == 240, f"unknown.dlx: expected 240, got {c}"


# ───────── Sudoku Solution ─────────

class TestSudokuSolution:
    @pytest.fixture(autouse=True)
    def load_solution(self):
        path = "/app/results/sudoku_solution.txt"
        assert os.path.exists(path), f"{path} does not exist"
        self.sol = open(path).read().strip()

    def test_format(self):
        assert len(self.sol) == 81, f"Expected 81 chars, got {len(self.sol)}"
        assert all(c in "123456789" for c in self.sol), "Must contain only digits 1-9"

    def test_rows(self):
        for r in range(9):
            row = set(self.sol[r * 9:(r + 1) * 9])
            assert row == set("123456789"), f"Row {r} invalid: {sorted(row)}"

    def test_columns(self):
        for c in range(9):
            col = set(self.sol[r * 9 + c] for r in range(9))
            assert col == set("123456789"), f"Column {c} invalid: {sorted(col)}"

    def test_blocks(self):
        for br in range(3):
            for bc in range(3):
                blk = set()
                for dr in range(3):
                    for dc in range(3):
                        blk.add(self.sol[(br * 3 + dr) * 9 + bc * 3 + dc])
                assert blk == set("123456789"), f"Block ({br},{bc}) invalid"

    def test_clues_match(self):
        for i in range(81):
            if PUZZLE[i] != "0":
                assert self.sol[i] == PUZZLE[i], \
                    f"Clue mismatch at pos {i}: puzzle={PUZZLE[i]}, solution={self.sol[i]}"

    def test_correct_answer(self):
        assert self.sol == SUDOKU_ANSWER, \
            f"Sudoku solution does not match known answer"


# ───────── Bug Report ─────────

class TestBugReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/results/bug_report.txt"
        assert os.path.exists(path), f"{path} does not exist"
        self.content = open(path).read().lower()

    def test_identifies_sudoku(self):
        assert "sudoku" in self.content, "Bug report should mention 'sudoku'"

    def test_identifies_block_issue(self):
        matches = any(
            term in self.content
            for term in ["block", "box", "transpose", "swap", "index", "formula"]
        )
        assert matches, "Bug report should mention the block/box constraint issue"


# ───────── Corrected DLX File ─────────

class TestCorrectedFile:
    def test_file_exists(self):
        assert os.path.exists("/app/results/corrected.dlx"), \
            "corrected.dlx does not exist"

    def test_has_content(self):
        content = open("/app/results/corrected.dlx").read().strip()
        assert len(content) > 100, "corrected.dlx appears too small"

    def test_correct_block_mapping(self):
        """Parse the corrected DLX file and verify standard Sudoku block mapping."""
        with open("/app/results/corrected.dlx") as f:
            lines = [
                l.strip() for l in f
                if l.strip() and not l.strip().startswith("|")
            ]

        checked = 0
        for line in lines[1:]:  # skip item header line
            items = line.split()
            cell_r, cell_c, block_idx = None, None, None
            for item in items:
                if len(item) == 3 and item[0] == "p" and item[1:].isdigit():
                    cell_r = int(item[1])
                    cell_c = int(item[2])
                elif len(item) == 3 and item[0] == "b" and item[1:].isdigit():
                    block_idx = int(item[1])

            if cell_r is not None and block_idx is not None:
                expected = (cell_r // 3) * 3 + cell_c // 3
                assert block_idx == expected, \
                    f"Cell ({cell_r},{cell_c}): block={block_idx}, expected={expected}"
                checked += 1

        assert checked > 0, "Could not parse any options from corrected.dlx"


# ───────── Unknown Analysis ─────────

class TestUnknownAnalysis:
    @pytest.fixture(autouse=True)
    def load_analysis(self):
        path = "/app/results/unknown_analysis.txt"
        assert os.path.exists(path), f"{path} does not exist"
        self.content = open(path).read()
        self.lower = self.content.lower()

    def test_identifies_structure(self):
        matches = any(
            term in self.lower
            for term in [
                "plus", "toroid", "5x5", "5×5", "wrap",
                "neighbor", "neighbour", "cross", "cardinal",
            ]
        )
        assert matches, \
            "Analysis should identify plus-shaped/toroidal/5x5 structure"

    def test_correct_count(self):
        assert "240" in self.content, \
            "Analysis should state the solution count of 240"
