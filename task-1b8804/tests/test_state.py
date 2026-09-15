
import subprocess
import os
import tempfile
import shutil
import sqlite3
import json
import re
import pytest


def parse_level(text):
    """Parse a Sokoban level from text into walls, boxes, goals, player."""
    walls = set()
    boxes = set()
    goals = set()
    player = None
    lines = text.strip().split("\n")
    lines = [l for l in lines if not l.strip().startswith(";")]
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            if ch == "#":
                walls.add((r, c))
            elif ch == "@":
                player = (r, c)
            elif ch == "+":
                player = (r, c)
                goals.add((r, c))
            elif ch == "$":
                boxes.add((r, c))
            elif ch == "*":
                boxes.add((r, c))
                goals.add((r, c))
            elif ch == ".":
                goals.add((r, c))
    return walls, boxes, goals, player


def verify_solution(level_text, solution):
    """Simulate a solution on a level and verify all goals are covered."""
    walls, boxes, goals, player = parse_level(level_text)
    assert player is not None, "No player (@) found in level"
    assert len(boxes) > 0, "No boxes ($) found in level"
    assert len(boxes) == len(goals), (
        f"Box count ({len(boxes)}) != goal count ({len(goals)})"
    )

    boxes = set(boxes)
    pr, pc = player

    directions = {
        "u": (-1, 0), "d": (1, 0), "l": (0, -1), "r": (0, 1),
        "U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1),
    }

    for i, ch in enumerate(solution):
        assert ch in directions, f"Invalid character '{ch}' at position {i}"
        dr, dc = directions[ch]
        nr, nc = pr + dr, pc + dc

        if ch.isupper():
            assert (nr, nc) in boxes, (
                f"Step {i} push '{ch}': no box at ({nr},{nc}), "
                f"player at ({pr},{pc})"
            )
            br, bc = nr + dr, nc + dc
            assert (br, bc) not in walls, (
                f"Step {i} push '{ch}': wall at push destination ({br},{bc})"
            )
            assert (br, bc) not in boxes, (
                f"Step {i} push '{ch}': box at push destination ({br},{bc})"
            )
            boxes.remove((nr, nc))
            boxes.add((br, bc))
            pr, pc = nr, nc
        else:
            assert (nr, nc) not in walls, (
                f"Step {i} move '{ch}': wall at ({nr},{nc})"
            )
            assert (nr, nc) not in boxes, (
                f"Step {i} move '{ch}': box at ({nr},{nc})"
            )
            pr, pc = nr, nc

    uncovered = goals - boxes
    assert len(uncovered) == 0, (
        f"Solution incomplete: {len(uncovered)} goals uncovered at {uncovered}"
    )


def run_solver(level_file, timeout=180):
    """Run the solver on a level file and return the solution string."""
    result = subprocess.run(
        ["bash", "/app/solve.sh", level_file],
        capture_output=True, text=True, timeout=timeout, cwd="/app",
    )
    assert result.returncode == 0, (
        f"Solver exited with code {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )
    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    assert len(lines) > 0, "Solver produced no output"
    solution = None
    for line in reversed(lines):
        if line and all(c in "udlrUDLR" for c in line):
            solution = line
            break
    if solution is None:
        solution = lines[-1]
    return solution


def run_analyze(level_file, timeout=240):
    """Run analyze.sh on a level file."""
    result = subprocess.run(
        ["bash", "/app/analyze.sh", level_file],
        capture_output=True, text=True, timeout=timeout, cwd="/app",
    )
    assert result.returncode == 0, (
        f"analyze.sh exited with code {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )
    return result


# ---- Script existence ----


def test_scripts_exist():
    """Verify all required scripts exist and are executable."""
    for script in ["/app/solve.sh", "/app/analyze.sh", "/app/audit.sh"]:
        assert os.path.isfile(script), f"{script} does not exist"
        assert os.access(script, os.X_OK), f"{script} is not executable"


# ---- Audit tests ----


def test_audit_provided_levels():
    """Test audit.sh correctly classifies all provided levels."""
    result = subprocess.run(
        ["bash", "/app/audit.sh", "/data/levels"],
        capture_output=True, text=True, timeout=120, cwd="/app",
    )
    assert result.returncode == 0, (
        f"audit.sh failed: {result.stderr[:500]}"
    )

    assert os.path.isfile("/app/audit_results.json"), (
        "audit_results.json not created"
    )
    with open("/app/audit_results.json") as f:
        results = json.load(f)

    expected = {
        "level_01.txt": "solvable",
        "level_02.txt": "solvable",
        "level_03.txt": "malformed",
        "level_04.txt": "malformed",
        "level_05.txt": "unsolvable",
        "level_06.txt": "solvable",
        "level_07.txt": "unsolvable",
    }
    for fname, expected_status in expected.items():
        assert fname in results, (
            f"Missing entry for {fname} in audit results"
        )
        actual = results[fname]["status"]
        assert actual == expected_status, (
            f"{fname}: expected '{expected_status}', got '{actual}'. "
            f"Reason: {results[fname].get('reason', 'N/A')}"
        )


def test_audit_hidden_levels():
    """Test audit.sh on hidden levels not in /data/levels/."""
    hidden_solvable = (
        "######\n"
        "#    #\n"
        "# $. #\n"
        "#  @ #\n"
        "######\n"
    )
    hidden_malformed = (
        "######\n"
        "# $  #\n"
        "# $. #\n"
        "#  @ #\n"
        "######\n"
    )
    hidden_unsolvable = (
        "#####\n"
        "#  .#\n"
        "# $.#\n"
        "#$@ #\n"
        "#####\n"
    )

    tmpdir = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmpdir, "h_solvable.txt"), "w") as f:
            f.write(hidden_solvable)
        with open(os.path.join(tmpdir, "h_malformed.txt"), "w") as f:
            f.write(hidden_malformed)
        with open(os.path.join(tmpdir, "h_unsolvable.txt"), "w") as f:
            f.write(hidden_unsolvable)

        result = subprocess.run(
            ["bash", "/app/audit.sh", tmpdir],
            capture_output=True, text=True, timeout=120, cwd="/app",
        )
        assert result.returncode == 0, (
            f"audit.sh failed on hidden levels: {result.stderr[:500]}"
        )

        with open("/app/audit_results.json") as f:
            results = json.load(f)

        assert results["h_solvable.txt"]["status"] == "solvable", (
            f"Hidden solvable misclassified as: "
            f"{results.get('h_solvable.txt', {}).get('status')}"
        )
        assert results["h_malformed.txt"]["status"] == "malformed", (
            f"Hidden malformed misclassified as: "
            f"{results.get('h_malformed.txt', {}).get('status')}"
        )
        assert results["h_unsolvable.txt"]["status"] == "unsolvable", (
            f"Hidden unsolvable misclassified as: "
            f"{results.get('h_unsolvable.txt', {}).get('status')}"
        )
    finally:
        shutil.rmtree(tmpdir)


# ---- Solver correctness ----


def test_solver_level_01():
    """Test solver on level_01 (3 boxes)."""
    level_file = "/data/levels/level_01.txt"
    with open(level_file) as f:
        level_text = f.read()
    solution = run_solver(level_file, timeout=60)
    verify_solution(level_text, solution)


def test_solver_level_02():
    """Test solver on level_02 (2 boxes)."""
    level_file = "/data/levels/level_02.txt"
    with open(level_file) as f:
        level_text = f.read()
    solution = run_solver(level_file, timeout=60)
    verify_solution(level_text, solution)


def test_solver_level_06():
    """Test solver on XSokoban Level 1 (6 boxes)."""
    level_file = "/data/levels/level_06.txt"
    with open(level_file) as f:
        level_text = f.read()
    solution = run_solver(level_file, timeout=240)
    verify_solution(level_text, solution)


def test_solver_hidden():
    """Test solver on a hidden level not present in /data/levels/."""
    hidden_level = (
        "######\n"
        "#    #\n"
        "# $  #\n"
        "# .  #\n"
        "# .  #\n"
        "# $  #\n"
        "#  @ #\n"
        "######\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        f.write(hidden_level)
        tmp_file = f.name
    try:
        solution = run_solver(tmp_file, timeout=60)
        verify_solution(hidden_level, solution)
    finally:
        os.unlink(tmp_file)


# ---- Pipeline integration ----


@pytest.fixture(scope="module")
def pipeline_run():
    """Run analyze.sh on level_01 once for all pipeline tests."""
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    for fp in ["/app/viz/level_01.dot", "/app/viz/level_01.svg"]:
        if os.path.exists(fp):
            os.remove(fp)

    result = subprocess.run(
        ["bash", "/app/analyze.sh", "/data/levels/level_01.txt"],
        capture_output=True, text=True, timeout=240, cwd="/app",
    )
    assert result.returncode == 0, (
        f"analyze.sh failed: {result.stderr[:500]}"
    )
    return db_path


def test_database_schema(pipeline_run):
    """Verify SQLite database has correct table and columns."""
    db_path = pipeline_run
    assert os.path.isfile(db_path), f"{db_path} not created"
    conn = sqlite3.connect(db_path)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = [t[0] for t in tables]
    assert "solutions" in table_names, (
        f"No 'solutions' table found, got: {table_names}"
    )

    cols = conn.execute("PRAGMA table_info(solutions)").fetchall()
    col_names = [c[1] for c in cols]
    for expected in ["level_file", "solution", "num_moves", "num_pushes",
                     "solved_at"]:
        assert expected in col_names, (
            f"Missing column '{expected}', found: {col_names}"
        )
    conn.close()


def test_database_data(pipeline_run):
    """Verify database contains correct self-consistent data."""
    db_path = pipeline_run
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT level_file, solution, num_moves, num_pushes "
        "FROM solutions WHERE level_file='level_01.txt'"
    ).fetchall()
    conn.close()

    assert len(rows) >= 1, "No level_01.txt entry in solutions table"
    row = rows[0]
    assert row[0] == "level_01.txt"

    solution = row[1]
    assert len(solution) > 0, "Empty solution string in database"
    assert all(c in "udlrUDLR" for c in solution), (
        "Solution contains invalid characters"
    )

    assert row[2] == len(solution), (
        f"num_moves ({row[2]}) != len(solution) ({len(solution)})"
    )

    actual_pushes = sum(1 for c in solution if c.isupper())
    assert row[3] == actual_pushes, (
        f"num_pushes ({row[3]}) != actual uppercase count ({actual_pushes})"
    )

    with open("/data/levels/level_01.txt") as f:
        level_text = f.read()
    verify_solution(level_text, solution)


def test_dot_structure(pipeline_run):
    """Verify DOT file has correct graph structure."""
    dot_path = "/app/viz/level_01.dot"
    assert os.path.isfile(dot_path), f"{dot_path} not found"

    with open(dot_path) as f:
        content = f.read()

    assert "digraph" in content, "DOT file missing 'digraph' keyword"
    assert "#" in content, (
        "DOT node labels should contain wall characters from board state"
    )

    content_lines = content.split("\n")
    node_count = sum(
        1 for l in content_lines
        if "[label=" in l and "->" not in l
    )
    assert node_count >= 2, (
        f"Expected at least 2 nodes, found {node_count}"
    )

    edges = re.findall(r'\w+\s*->\s*\w+', content)
    assert len(edges) >= 1, f"Expected at least 1 edge, found {len(edges)}"
    assert len(edges) == node_count - 1, (
        f"Expected {node_count - 1} edges for {node_count} nodes, "
        f"found {len(edges)}"
    )

    push_labels = re.findall(
        r'label="(push (?:up|down|left|right))"', content
    )
    assert len(push_labels) == len(edges), (
        f"Expected {len(edges)} push direction labels, "
        f"found {len(push_labels)}"
    )


def test_svg_generated(pipeline_run):
    """Verify SVG file is generated and contains valid markup."""
    svg_path = "/app/viz/level_01.svg"
    assert os.path.isfile(svg_path), f"{svg_path} not found"

    with open(svg_path) as f:
        content = f.read()

    assert len(content) > 100, "SVG file too small, likely empty or corrupt"
    assert "<svg" in content, "SVG file missing <svg tag"


def test_dot_node_count(pipeline_run):
    """Verify DOT node count equals num_pushes + 1."""
    db_path = pipeline_run
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT num_pushes FROM solutions WHERE level_file='level_01.txt'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1, "No level_01.txt entry in database"
    num_pushes = rows[0][0]

    dot_path = "/app/viz/level_01.dot"
    with open(dot_path) as f:
        content = f.read()

    content_lines = content.split("\n")
    node_count = sum(
        1 for l in content_lines
        if "[label=" in l and "->" not in l
    )
    expected = num_pushes + 1
    assert node_count == expected, (
        f"Expected {expected} nodes (num_pushes={num_pushes} + 1), "
        f"found {node_count}"
    )


# ---- Hidden pipeline end-to-end ----


def test_pipeline_hidden():
    """Full pipeline test on a hidden 1-box level."""
    hidden_level = (
        "########\n"
        "#      #\n"
        "# .$ @ #\n"
        "#      #\n"
        "########\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir="/tmp"
    ) as f:
        f.write(hidden_level)
        tmp = f.name

    basename = os.path.splitext(os.path.basename(tmp))[0]

    try:
        run_analyze(tmp, timeout=120)

        db_path = "/app/results.db"
        assert os.path.isfile(db_path), "Database not found after analyze"
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT solution, num_moves, num_pushes FROM solutions "
            "WHERE level_file=?",
            (os.path.basename(tmp),)
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, "Hidden level not found in database"
        solution, num_moves, num_pushes = rows[0]
        verify_solution(hidden_level, solution)
        assert num_moves == len(solution), (
            f"num_moves ({num_moves}) != len(solution) ({len(solution)})"
        )
        assert num_pushes == sum(1 for c in solution if c.isupper()), (
            "num_pushes mismatch"
        )

        dot_path = f"/app/viz/{basename}.dot"
        svg_path = f"/app/viz/{basename}.svg"
        assert os.path.isfile(dot_path), f"DOT not found: {dot_path}"
        assert os.path.isfile(svg_path), f"SVG not found: {svg_path}"

        with open(dot_path) as f:
            dot_content = f.read()
        assert "digraph" in dot_content, "Hidden DOT missing digraph"

        dot_lines = dot_content.split("\n")
        node_count = sum(
            1 for l in dot_lines
            if "[label=" in l and "->" not in l
        )
        expected_nodes = num_pushes + 1
        assert node_count == expected_nodes, (
            f"Expected {expected_nodes} nodes, found {node_count}"
        )
    finally:
        os.unlink(tmp)
