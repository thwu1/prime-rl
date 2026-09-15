#!/usr/bin/env python3
"""Tests for Sokoban tournament solutions stored in the database."""

import os
import json
import sqlite3
import pytest

DB_PATH = "/app/sokoban.db"
CONFIG_PATH = "/app/config.json"
REPORT_PATH = "/app/report.json"
LEVEL_IDS = [1, 2, 3, 4]


def get_constraints():
    """Load per-level constraints from config.json."""
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    return {lvl['id']: lvl for lvl in config['levels']}


def parse_level_from_db(level_id):
    """Reconstruct level state from normalized cell records in the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cells = c.execute(
        'SELECT row, col, cell_type FROM cells WHERE level_id = ?',
        (level_id,)
    ).fetchall()
    conn.close()

    walls = set()
    boxes = set()
    goals = set()
    player = None

    for row, col, cell_type in cells:
        if cell_type == 'wall':
            walls.add((row, col))
        elif cell_type == 'box':
            boxes.add((row, col))
        elif cell_type == 'goal':
            goals.add((row, col))
        elif cell_type == 'player':
            player = (row, col)
        elif cell_type == 'player_on_goal':
            player = (row, col)
            goals.add((row, col))
        elif cell_type == 'box_on_goal':
            boxes.add((row, col))
            goals.add((row, col))

    return walls, boxes, goals, player


def simulate(walls, boxes, goals, player, moves):
    """Simulate a move sequence. Returns (success, push_count, message)."""
    dir_map = {
        'u': (-1, 0), 'd': (1, 0), 'l': (0, -1), 'r': (0, 1),
        'U': (-1, 0), 'D': (1, 0), 'L': (0, -1), 'R': (0, 1),
    }

    boxes = set(boxes)
    pr, pc = player
    pushes = 0

    for i, ch in enumerate(moves):
        if ch not in dir_map:
            return False, pushes, f"Invalid character '{ch}' at position {i}"
        dr, dc = dir_map[ch]
        nr, nc = pr + dr, pc + dc
        if (nr, nc) in walls:
            return False, pushes, f"Move {i}: walked into wall at ({nr},{nc})"
        if (nr, nc) in boxes:
            bnr, bnc = nr + dr, nc + dc
            if (bnr, bnc) in walls:
                return False, pushes, f"Move {i}: pushed box into wall at ({bnr},{bnc})"
            if (bnr, bnc) in boxes:
                return False, pushes, f"Move {i}: pushed box into box at ({bnr},{bnc})"
            boxes.remove((nr, nc))
            boxes.add((bnr, bnc))
            pushes += 1
        pr, pc = nr, nc

    if boxes == goals:
        return True, pushes, f"Solved with {pushes} pushes in {len(moves)} moves"
    remaining = len(boxes - goals)
    return False, pushes, f"{remaining} box(es) not on goals after all moves"


@pytest.mark.parametrize("level_id", LEVEL_IDS)
def test_solution_exists_in_db(level_id):
    """Solution must be recorded in the database solutions table."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute(
        'SELECT moves, push_count, move_count FROM solutions WHERE level_id = ?',
        (level_id,)
    ).fetchone()
    conn.close()
    assert row is not None, f"No solution in DB for level {level_id}"
    moves, push_count, move_count = row
    assert len(moves.strip()) > 0, f"Empty solution for level {level_id}"
    assert push_count > 0, f"push_count must be positive for level {level_id}"
    assert move_count > 0, f"move_count must be positive for level {level_id}"


@pytest.mark.parametrize("level_id", LEVEL_IDS)
def test_solution_valid(level_id):
    """Solution must solve the level within per-level constraints."""
    constraints = get_constraints()
    cons = constraints[level_id]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute(
        'SELECT moves FROM solutions WHERE level_id = ?',
        (level_id,)
    ).fetchone()
    conn.close()
    assert row is not None, f"No solution for level {level_id}"

    moves = row[0].strip()
    walls, boxes, goals, player = parse_level_from_db(level_id)

    assert len(moves) <= cons['max_moves'], (
        f"Level {level_id}: {len(moves)} moves exceeds limit {cons['max_moves']}"
    )

    success, pushes, msg = simulate(walls, boxes, goals, player, moves)
    assert success, f"Level {level_id}: {msg}"
    assert pushes <= cons['max_pushes'], (
        f"Level {level_id}: {pushes} pushes exceeds limit {cons['max_pushes']}"
    )


@pytest.mark.parametrize("level_id", LEVEL_IDS)
def test_solution_counts_accurate(level_id):
    """Recorded push_count and move_count must match actual simulation."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute(
        'SELECT moves, push_count, move_count FROM solutions WHERE level_id = ?',
        (level_id,)
    ).fetchone()
    conn.close()
    assert row is not None, f"No solution for level {level_id}"

    moves_str, recorded_pushes, recorded_moves = row
    moves_str = moves_str.strip()

    walls, boxes, goals, player = parse_level_from_db(level_id)
    success, actual_pushes, _ = simulate(walls, boxes, goals, player, moves_str)
    assert success, f"Level {level_id}: solution is invalid"

    assert recorded_pushes == actual_pushes, (
        f"Level {level_id}: recorded push_count {recorded_pushes} != actual {actual_pushes}"
    )
    assert recorded_moves == len(moves_str), (
        f"Level {level_id}: recorded move_count {recorded_moves} != actual {len(moves_str)}"
    )


def test_report_exists():
    """Validation report JSON must exist at the expected path."""
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"


def test_report_valid():
    """Validation report must show all four levels passed."""
    with open(REPORT_PATH) as f:
        report = json.load(f)

    assert "all_passed" in report, "Report missing 'all_passed' field"
    assert report["all_passed"] is True, "Report shows not all levels passed"

    assert "results" in report, "Report missing 'results' field"
    assert len(report["results"]) == len(LEVEL_IDS), (
        f"Expected {len(LEVEL_IDS)} results, got {len(report['results'])}"
    )

    for result in report["results"]:
        assert result["status"] == "pass", (
            f"Level {result['level_id']}: {result.get('reason', 'unknown error')}"
        )


def test_database_integrity():
    """Database must have correct structure and complete level data."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Verify all expected tables exist
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert 'levels' in tables, "Missing 'levels' table"
    assert 'cells' in tables, "Missing 'cells' table"
    assert 'solutions' in tables, "Missing 'solutions' table"

    # Verify all 4 levels still present
    level_count = c.execute('SELECT COUNT(*) FROM levels').fetchone()[0]
    assert level_count == 4, f"Expected 4 levels, found {level_count}"

    # Verify solutions count
    sol_count = c.execute('SELECT COUNT(*) FROM solutions').fetchone()[0]
    assert sol_count == 4, f"Expected 4 solutions, found {sol_count}"

    conn.close()
