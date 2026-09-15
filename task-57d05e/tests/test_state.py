"""Tests for WCA FMC Multi-Tool Analysis Pipeline."""

import json
import os
import re
import sqlite3
import subprocess
from collections import Counter

import pytest

# ---------------------------------------------------------------------------
# Independent Rubik's Cube state simulator (cycle-based permutations)
# Facelet order: URFDLB, 9 per face, reading order from outside each face.
# Cycles are (a, b, c, d) meaning: new[b]=old[a], new[c]=old[b], ...
# ---------------------------------------------------------------------------

SOLVED = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

MOVE_CYCLES = {
    "U": [(0, 2, 8, 6), (1, 5, 7, 3), (18, 36, 45, 9), (19, 37, 46, 10), (20, 38, 47, 11)],
    "R": [(9, 11, 17, 15), (10, 14, 16, 12), (8, 45, 35, 26), (5, 48, 32, 23), (2, 51, 29, 20)],
    "F": [(18, 20, 26, 24), (19, 23, 25, 21), (6, 9, 29, 44), (7, 12, 28, 41), (8, 15, 27, 38)],
    "D": [(27, 29, 35, 33), (28, 32, 34, 30), (24, 15, 51, 42), (44, 26, 17, 53), (25, 16, 52, 43)],
    "L": [(36, 38, 44, 42), (37, 41, 43, 39), (0, 18, 27, 53), (3, 21, 30, 50), (6, 24, 33, 47)],
    "B": [(45, 47, 53, 51), (46, 50, 52, 48), (2, 36, 33, 17), (1, 39, 34, 14), (0, 42, 35, 11)],
}


def _apply_cycles(state, cycles, times=1):
    for _ in range(times % 4):
        new = list(state)
        for cycle in cycles:
            n = len(cycle)
            for i in range(n):
                new[cycle[(i + 1) % n]] = state[cycle[i]]
        state = new
    return state


def _parse_move(token):
    token = token.strip()
    if not token:
        raise ValueError("Empty move token")
    base = token[0]
    if base not in MOVE_CYCLES:
        raise ValueError(f"Unknown face: {base}")
    suffix = token[1:]
    if suffix == "":
        return base, 1
    elif suffix in ("'", "\u2019"):
        return base, 3
    elif suffix == "2":
        return base, 2
    elif suffix == "1":
        return base, 1
    elif suffix == "3":
        return base, 3
    else:
        raise ValueError(f"Unknown move suffix: {suffix!r}")


def apply_sequence(state_str, sequence):
    state = list(state_str)
    for token in sequence.split():
        face, times = _parse_move(token)
        state = _apply_cycles(state, MOVE_CYCLES[face], times)
    return "".join(state)


# ---------------------------------------------------------------------------
# Simulator self-tests
# ---------------------------------------------------------------------------


def test_simulator_identity():
    for face in "URFDLB":
        s = list(SOLVED)
        for _ in range(4):
            s = _apply_cycles(s, MOVE_CYCLES[face], 1)
        assert "".join(s) == SOLVED, f"{face}^4 != identity"


def test_simulator_sexy_move():
    s = SOLVED
    for _ in range(6):
        s = apply_sequence(s, "R U R' U'")
    assert s == SOLVED


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_stats():
    path = "/app/output/db_stats.json"
    assert os.path.exists(path), f"{path} does not exist"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def scramble_analysis():
    path = "/app/output/scramble_analysis.json"
    assert os.path.exists(path), f"{path} does not exist"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def target_scrambles():
    with open("/app/data/target_scrambles.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Database existence and schema tests
# ---------------------------------------------------------------------------


def test_database_exists():
    assert os.path.exists("/app/fmc.db"), "SQLite database /app/fmc.db does not exist"


def test_database_tables():
    conn = sqlite3.connect("/app/fmc.db")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    conn.close()
    assert "results" in tables, "Missing 'results' table"
    assert "scrambles" in tables, "Missing 'scrambles' table"


def test_database_results_row_count():
    conn = sqlite3.connect("/app/fmc.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM results")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 5756, f"Expected 5756 result rows, got {count}"


def test_database_scrambles_row_count():
    conn = sqlite3.connect("/app/fmc.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM scrambles")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 300, f"Expected 300 scramble rows, got {count}"


def test_database_best_is_integer():
    conn = sqlite3.connect("/app/fmc.db")
    cur = conn.cursor()
    cur.execute("SELECT typeof(best) FROM results LIMIT 1")
    col_type = cur.fetchone()[0]
    conn.close()
    assert col_type == "integer", f"best column type is {col_type}, expected integer"


# ---------------------------------------------------------------------------
# Database stats tests
# ---------------------------------------------------------------------------


def test_db_stats_exists():
    assert os.path.exists("/app/output/db_stats.json")


def test_db_stats_total_rows(db_stats):
    assert db_stats["total_result_rows"] == 5756


def test_db_stats_valid_results(db_stats):
    assert db_stats["valid_results"] == 5685


def test_db_stats_unique_competitors(db_stats):
    assert db_stats["unique_competitors"] == 837


def test_db_stats_unique_competitions(db_stats):
    assert db_stats["unique_competitions"] == 1508


def test_db_stats_best_single(db_stats):
    assert db_stats["best_single_ever"] == 16


def test_db_stats_sub20(db_stats):
    assert db_stats["sub20_count"] == 190


def test_db_stats_median(db_stats):
    assert db_stats["median_single"] == 23


def test_db_stats_top5_structure(db_stats):
    top5 = db_stats["top5_singles"]
    assert isinstance(top5, list)
    assert len(top5) >= 5
    for entry in top5[:5]:
        assert "person_name" in entry
        assert "best" in entry
        assert "competition_id" in entry


def test_db_stats_top5_values(db_stats):
    top5 = db_stats["top5_singles"]
    bests = [e["best"] for e in top5[:5]]
    assert bests[0] == 16, f"Top single should be 16, got {bests[0]}"
    assert all(b <= 17 for b in bests[:5]), f"Top 5 should all be <=17, got {bests}"


def test_db_stats_records_count(db_stats):
    # Independently count from DB
    conn = sqlite3.connect("/app/fmc.db")
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM results WHERE regional_single_record != 'NULL' AND regional_single_record != ''"
    )
    expected = cur.fetchone()[0]
    conn.close()
    assert db_stats["records_count"] == expected


def test_db_stats_scramble_count(db_stats):
    assert db_stats["scramble_count"] == 300


# ---------------------------------------------------------------------------
# Scramble analysis output tests
# ---------------------------------------------------------------------------


def test_scramble_analysis_exists():
    assert os.path.exists("/app/output/scramble_analysis.json")


def test_scramble_analysis_count(scramble_analysis):
    assert len(scramble_analysis) == 5, f"Expected 5 entries, got {len(scramble_analysis)}"


def test_scramble_analysis_fields(scramble_analysis):
    required = {
        "competition_id", "scramble_num", "scramble", "facelet_string",
        "kociemba_solution", "kociemba_length", "verified",
        "inverse_solution", "inverse_length",
    }
    for entry in scramble_analysis:
        missing = required - set(entry.keys())
        assert not missing, f"Missing fields: {missing}"


# ---------------------------------------------------------------------------
# Facelet string tests
# ---------------------------------------------------------------------------


def test_facelet_strings_valid(scramble_analysis):
    for entry in scramble_analysis:
        fs = entry["facelet_string"]
        assert len(fs) == 54, f"Facelet string length {len(fs)} != 54"
        assert set(fs) <= set("URFDLB"), f"Invalid chars in facelet string"
        c = Counter(fs)
        for ch in "URFDLB":
            assert c[ch] == 9, f"Expected 9 of '{ch}', got {c[ch]}"


def test_facelet_strings_correct(scramble_analysis):
    for entry in scramble_analysis:
        expected = apply_sequence(SOLVED, entry["scramble"])
        assert entry["facelet_string"] == expected, (
            f"Facelet mismatch for {entry['competition_id']} #{entry['scramble_num']}.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {entry['facelet_string']}"
        )


# ---------------------------------------------------------------------------
# Kociemba solution tests
# ---------------------------------------------------------------------------

MOVE_PATTERN = re.compile(r"^[URFDLB][2']?$")


def test_kociemba_solution_notation(scramble_analysis):
    for entry in scramble_analysis:
        sol = entry["kociemba_solution"].strip()
        if not sol:
            continue
        for m in sol.split():
            assert MOVE_PATTERN.match(m), (
                f"Invalid move '{m}' in kociemba solution for "
                f"{entry['competition_id']} #{entry['scramble_num']}"
            )


def test_kociemba_solutions_valid(scramble_analysis):
    for entry in scramble_analysis:
        scrambled = apply_sequence(SOLVED, entry["scramble"])
        result = apply_sequence(scrambled, entry["kociemba_solution"])
        assert result == SOLVED, (
            f"Kociemba solution doesn't solve {entry['competition_id']} #{entry['scramble_num']}.\n"
            f"  After solution: {result}"
        )


def test_kociemba_lengths(scramble_analysis):
    for entry in scramble_analysis:
        moves = entry["kociemba_solution"].strip().split()
        assert entry["kociemba_length"] == len(moves), (
            f"Length mismatch: claimed {entry['kociemba_length']}, actual {len(moves)}"
        )


def test_kociemba_length_reasonable(scramble_analysis):
    """Kociemba two-phase typically finds solutions under 22 moves."""
    for entry in scramble_analysis:
        assert entry["kociemba_length"] <= 25, (
            f"Kociemba solution too long: {entry['kociemba_length']} moves"
        )


# ---------------------------------------------------------------------------
# Inverse solution tests
# ---------------------------------------------------------------------------


def test_inverse_solutions_valid(scramble_analysis):
    for entry in scramble_analysis:
        scrambled = apply_sequence(SOLVED, entry["scramble"])
        result = apply_sequence(scrambled, entry["inverse_solution"])
        assert result == SOLVED, (
            f"Inverse solution doesn't solve {entry['competition_id']} #{entry['scramble_num']}"
        )


def test_inverse_lengths(scramble_analysis):
    for entry in scramble_analysis:
        moves = entry["inverse_solution"].strip().split()
        assert entry["inverse_length"] == len(moves)


# ---------------------------------------------------------------------------
# Verified flag tests
# ---------------------------------------------------------------------------


def test_verified_flag(scramble_analysis):
    for entry in scramble_analysis:
        assert entry["verified"] is True, (
            f"verified should be True for {entry['competition_id']} #{entry['scramble_num']}"
        )


# ---------------------------------------------------------------------------
# Tool usage verification
# ---------------------------------------------------------------------------


def test_pipeline_script_exists():
    assert os.path.exists("/app/pipeline.py"), "pipeline.py must exist"


def test_pipeline_uses_multiple_tools():
    """Verify the pipeline integrates sqlite3, jq, and kociemba."""
    with open("/app/pipeline.py") as f:
        code = f.read()

    has_sqlite = "sqlite3" in code or "sqlite" in code
    has_jq = "jq" in code
    has_kociemba = "kociemba" in code

    assert has_sqlite, "pipeline.py should use sqlite3"
    assert has_jq, "pipeline.py should use jq"
    assert has_kociemba, "pipeline.py should use kociemba"
