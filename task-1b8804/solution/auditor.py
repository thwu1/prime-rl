#!/usr/bin/env python3
"""
Sokoban level auditor - classifies levels as solvable, unsolvable, or malformed
through structural and logical analysis of the level state.
"""

import sys
import os
import json


def parse_level(text):
    """Parse Sokoban level text into walls, boxes, goals, player."""
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


def is_corner_deadlock(pos, walls):
    """Check if a position is a corner formed by walls on two perpendicular sides."""
    r, c = pos
    u = (r - 1, c) in walls
    d = (r + 1, c) in walls
    l = (r, c - 1) in walls
    ri = (r, c + 1) in walls
    return (u and l) or (u and ri) or (d and l) or (d and ri)


def compute_dead_positions(walls, goals):
    """Compute positions where a box would be in a simple deadlock (corner or wall-edge)."""
    dead = set()
    if not walls:
        return dead
    max_r = max(r for r, c in walls) + 1
    max_c = max(c for r, c in walls) + 1

    # Corner deadlocks
    for r in range(max_r):
        for c in range(max_c):
            pos = (r, c)
            if pos in walls or pos in goals:
                continue
            if is_corner_deadlock(pos, walls):
                dead.add(pos)

    # Wall-edge deadlocks: closed segments along a wall with no goal
    checks = [(-1, 0, 0, 1), (1, 0, 0, 1), (0, -1, 1, 0), (0, 1, 1, 0)]
    visited_seg = set()
    for wall_dr, wall_dc, move_dr, move_dc in checks:
        for r in range(max_r):
            for c in range(max_c):
                pos = (r, c)
                if pos in walls or (pos, wall_dr, wall_dc) in visited_seg:
                    continue
                if (r + wall_dr, c + wall_dc) not in walls:
                    continue
                segment = []
                rr, cc = r, c
                while (
                    0 <= rr < max_r and 0 <= cc < max_c
                    and (rr, cc) not in walls
                    and (rr + wall_dr, cc + wall_dc) in walls
                ):
                    segment.append((rr, cc))
                    visited_seg.add(((rr, cc), wall_dr, wall_dc))
                    rr += move_dr
                    cc += move_dc
                if len(segment) < 2:
                    continue
                first, last = segment[0], segment[-1]
                before = (first[0] - move_dr, first[1] - move_dc)
                after = (last[0] + move_dr, last[1] + move_dc)
                if before in walls and after in walls:
                    if not any(p in goals for p in segment):
                        dead.update(segment)

    return dead


def classify_level(text):
    """Classify a Sokoban level as solvable, unsolvable, or malformed."""
    walls, boxes, goals, player = parse_level(text)

    # Malformation checks
    if player is None:
        return "malformed", "No player character found in level"

    if len(boxes) == 0 and len(goals) == 0:
        return "malformed", "No boxes or goals found in level"

    if len(boxes) != len(goals):
        return "malformed", (
            f"Box count ({len(boxes)}) does not match goal count ({len(goals)})"
        )

    if len(boxes) == 0:
        return "malformed", "No boxes found in level"

    # Check for initial deadlocks (corner and wall-edge)
    dead_pos = compute_dead_positions(walls, goals)
    for box in boxes:
        if box not in goals and box in dead_pos:
            return "unsolvable", (
                f"Box at ({box[0]},{box[1]}) is in a deadlock position"
            )

    return "solvable", "No structural issues detected"


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 auditor.py <directory>", file=sys.stderr)
        sys.exit(1)

    level_dir = sys.argv[1]
    results = {}

    for filename in sorted(os.listdir(level_dir)):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(level_dir, filename)
        try:
            with open(filepath) as f:
                text = f.read()
            status, reason = classify_level(text)
        except Exception as e:
            status, reason = "malformed", f"Error reading level: {str(e)}"
        results[filename] = {"status": status, "reason": reason}

    with open("/app/audit_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
