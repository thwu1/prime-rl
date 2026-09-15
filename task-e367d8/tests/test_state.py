"""
Verify the Sokoban benchmark results against the database targets.

"""

import json
import os
import sqlite3
import xml.etree.ElementTree as ET

DB_PATH = "/app/benchmark.db"
RESULTS_PATH = "/app/results.json"
REQUIRED_SOLVED = 8
TOTAL_TARGETS = 10

SSX_NS = "http://sokosolve.sourceforge.net/SokoSolveLibrary.xsd"

SSX_CHAR_MAP = {
    "~": None,
    "#": "#",
    ".": " ",
    "O": ".",
    "X": "$",
    "$": "*",
    "P": "@",
    "*": "+",
}


def parse_xsb_text(text):
    lines = [l.rstrip() for l in text.split("\n") if l.rstrip() and not l.startswith(";")]
    walls, goals, boxes = set(), set(), set()
    player = None
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            pos = (r, c)
            if ch == "#":
                walls.add(pos)
            elif ch == "@":
                player = pos
            elif ch == "+":
                player = pos
                goals.add(pos)
            elif ch == "$":
                boxes.add(pos)
            elif ch == "*":
                boxes.add(pos)
                goals.add(pos)
            elif ch == ".":
                goals.add(pos)
    return walls, player, boxes, goals


def ssx_rows_to_xsb(rows):
    xsb_lines = []
    for row in rows:
        line = ""
        for ch in row:
            mapped = SSX_CHAR_MAP.get(ch, ch)
            if mapped is not None:
                line += mapped
        xsb_lines.append(line.rstrip())
    return "\n".join(xsb_lines)


def extract_ssx_puzzle(ssx_path, puzzle_id):
    tree = ET.parse(ssx_path)
    root = tree.getroot()
    for puzzle in root.findall(".//{%s}Puzzle" % SSX_NS):
        if puzzle.get("PuzzleID") == puzzle_id:
            rows = []
            for row_elem in puzzle.findall(".//{%s}Row" % SSX_NS):
                if row_elem.text:
                    rows.append(row_elem.text)
            return ssx_rows_to_xsb(rows)
    return None


def load_puzzle(fmt, base_path, puzzle_ref):
    if fmt == "xsb":
        path = os.path.join(base_path, puzzle_ref)
        with open(path) as f:
            return f.read()
    elif fmt == "ssx":
        return extract_ssx_puzzle(base_path, puzzle_ref)
    return None


def verify_solution(walls, player, boxes, goals, solution):
    boxes = set(boxes)
    pr, pc = player
    pushes = 0
    dirs = {
        "u": (-1, 0), "d": (1, 0), "l": (0, -1), "r": (0, 1),
        "U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1),
    }
    for ch in solution:
        if ch not in dirs:
            return False, 0
        dr, dc = dirs[ch]
        nr, nc = pr + dr, pc + dc
        if (nr, nc) in walls:
            return False, 0
        if (nr, nc) in boxes:
            br, bc = nr + dr, nc + dc
            if (br, bc) in walls or (br, bc) in boxes:
                return False, 0
            boxes.remove((nr, nc))
            boxes.add((br, bc))
            pushes += 1
        pr, pc = nr, nc
    solved = boxes == goals or (boxes.issubset(goals) and len(boxes) == len(goals))
    return solved, pushes


def test_results_file_exists():
    """Results file must exist and be valid JSON array."""
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        results = json.load(f)
    assert isinstance(results, list), "results.json must be a JSON array"
    for entry in results:
        assert "target_id" in entry, "Each result entry must have 'target_id'"
        assert "solution" in entry, "Each result entry must have 'solution'"
        assert isinstance(entry["solution"], str), "solution must be a string"


def test_solutions_valid_and_sufficient():
    """Solutions must be valid and meet push thresholds; at least 8/10 must pass."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    targets = conn.execute(
        "SELECT t.target_id, t.puzzle_ref, t.max_pushes, t.time_limit_sec, "
        "c.format, c.base_path "
        "FROM targets t JOIN collections c ON t.collection_id = c.id"
    ).fetchall()
    conn.close()

    with open(RESULTS_PATH) as f:
        results = json.load(f)

    result_map = {r["target_id"]: r["solution"] for r in results}

    solved = 0
    details = []

    for target in targets:
        tid = target["target_id"]
        if tid not in result_map:
            details.append(f"{tid}: NO RESULT SUBMITTED")
            continue

        solution_str = result_map[tid]
        puzzle_text = load_puzzle(target["format"], target["base_path"], target["puzzle_ref"])
        assert puzzle_text is not None, f"{tid}: could not load puzzle {target['puzzle_ref']}"

        walls, player, boxes, goals = parse_xsb_text(puzzle_text)
        assert player is not None, f"{tid}: no player found in puzzle"
        assert len(boxes) > 0, f"{tid}: no boxes found in puzzle"
        assert len(boxes) == len(goals), f"{tid}: box/goal mismatch ({len(boxes)} vs {len(goals)})"

        valid, pushes = verify_solution(walls, player, boxes, goals, solution_str)

        if valid and pushes <= target["max_pushes"]:
            solved += 1
            details.append(
                f"{tid}: PASS ({pushes} pushes, limit {target['max_pushes']})"
            )
        elif valid:
            details.append(
                f"{tid}: FAIL - too many pushes ({pushes} > {target['max_pushes']})"
            )
        else:
            details.append(f"{tid}: FAIL - invalid solution")

    report = "\n".join(details)
    report += f"\n\nSolved: {solved}/{TOTAL_TARGETS} (need {REQUIRED_SOLVED})"
    print(report)

    assert solved >= REQUIRED_SOLVED, (
        f"Only solved {solved}/{TOTAL_TARGETS}, need {REQUIRED_SOLVED}\n{report}"
    )
