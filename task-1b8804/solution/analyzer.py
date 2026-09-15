#!/usr/bin/env python3
"""
Sokoban analysis pipeline: solve a level, store results in SQLite,
generate Graphviz DOT visualization, and render to SVG.
"""

import sys
import os
import subprocess
import sqlite3


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


def render_board(walls, boxes, goals, player, max_r, max_c):
    """Render board state as ASCII string."""
    lines = []
    for r in range(max_r + 1):
        line = []
        for c in range(max_c + 1):
            pos = (r, c)
            if pos == player and pos in goals:
                line.append("+")
            elif pos == player:
                line.append("@")
            elif pos in boxes and pos in goals:
                line.append("*")
            elif pos in boxes:
                line.append("$")
            elif pos in goals:
                line.append(".")
            elif pos in walls:
                line.append("#")
            else:
                line.append(" ")
        lines.append("".join(line).rstrip())
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def simulate_and_record(level_text, solution):
    """Simulate solution, return board states after each push and push chars."""
    walls, boxes, goals, player = parse_level(level_text)
    boxes = set(boxes)
    pr, pc = player

    max_r = max(r for r, _ in walls) if walls else 0
    max_c = max(c for _, c in walls) if walls else 0

    directions = {
        "u": (-1, 0), "d": (1, 0), "l": (0, -1), "r": (0, 1),
        "U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1),
    }

    states = [render_board(walls, boxes, goals, (pr, pc), max_r, max_c)]
    push_chars = []

    for ch in solution:
        dr, dc = directions[ch]
        nr, nc = pr + dr, pc + dc
        if ch.isupper():
            br, bc = nr + dr, nc + dc
            boxes.remove((nr, nc))
            boxes.add((br, bc))
            pr, pc = nr, nc
            states.append(
                render_board(walls, boxes, goals, (pr, pc), max_r, max_c)
            )
            push_chars.append(ch)
        else:
            pr, pc = nr, nc

    return states, push_chars


def generate_dot(states, push_chars):
    """Generate Graphviz DOT content for the solution trace."""
    lines = ["digraph solution {"]
    lines.append('  rankdir=TB;')
    lines.append('  node [shape=box, fontname="Courier"];')

    for i, state in enumerate(states):
        escaped = state.replace("\\", "\\\\").replace('"', '\\"')
        label = escaped.replace("\n", "\\l") + "\\l"
        lines.append(f'  s{i} [label="{label}"];')

    push_labels = {
        "U": "push up", "D": "push down",
        "L": "push left", "R": "push right",
    }
    for i, ch in enumerate(push_chars):
        lines.append(f'  s{i} -> s{i + 1} [label="{push_labels[ch]}"];')

    lines.append("}")
    return "\n".join(lines)


def store_in_database(db_path, level_file, solution, num_moves, num_pushes):
    """Store solution data in SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS solutions ("
        "  level_file TEXT,"
        "  solution TEXT,"
        "  num_moves INTEGER,"
        "  num_pushes INTEGER,"
        "  solved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.execute(
        "INSERT INTO solutions (level_file, solution, num_moves, num_pushes) "
        "VALUES (?, ?, ?, ?)",
        (os.path.basename(level_file), solution, num_moves, num_pushes),
    )
    conn.commit()
    conn.close()


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 analyzer.py <level_file>", file=sys.stderr)
        sys.exit(1)

    level_file = sys.argv[1]
    basename = os.path.splitext(os.path.basename(level_file))[0]

    # Run solver
    result = subprocess.run(
        ["bash", "/app/solve.sh", level_file],
        capture_output=True, text=True, timeout=200, cwd="/app",
    )
    if result.returncode != 0:
        print(f"Solver failed: {result.stderr[:500]}", file=sys.stderr)
        sys.exit(1)

    # Extract solution from last valid line of output
    output_lines = result.stdout.strip().split("\n")
    solution = None
    for line in reversed(output_lines):
        line = line.strip()
        if line and all(c in "udlrUDLR" for c in line):
            solution = line
            break
    if solution is None:
        print("No valid solution in solver output", file=sys.stderr)
        sys.exit(1)

    num_moves = len(solution)
    num_pushes = sum(1 for c in solution if c.isupper())

    # Store in SQLite database
    store_in_database("/app/results.db", level_file, solution,
                      num_moves, num_pushes)

    # Generate visualization
    with open(level_file) as f:
        level_text = f.read()

    states, push_chars = simulate_and_record(level_text, solution)

    os.makedirs("/app/viz", exist_ok=True)
    dot_path = f"/app/viz/{basename}.dot"
    svg_path = f"/app/viz/{basename}.svg"

    dot_content = generate_dot(states, push_chars)
    with open(dot_path, "w") as f:
        f.write(dot_content)

    # Render DOT to SVG using Graphviz
    render_result = subprocess.run(
        ["dot", "-Tsvg", "-o", svg_path, dot_path],
        capture_output=True, text=True,
    )
    if render_result.returncode != 0:
        print(f"Graphviz failed: {render_result.stderr[:500]}", file=sys.stderr)
        sys.exit(1)

    # Output the solution
    print(solution)


if __name__ == "__main__":
    main()
