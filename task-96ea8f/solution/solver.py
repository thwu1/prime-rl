#!/usr/bin/env python3
"""
ARC-AGI Batch Solver: infers transformation rules from training examples
and applies them to produce correct test outputs for 6 ARC tasks.

Each task requires a different algorithm — the solver analyzes structural
properties of each task to select the appropriate transformation.
"""

import json
import os
from collections import deque


def load_task(path):
    with open(path) as f:
        return json.load(f)


def classify_task(task):
    """Analyze task properties to determine which solver to use."""
    train = task["train"]
    ex0 = train[0]
    inp, out = ex0["input"], ex0["output"]
    in_rows, in_cols = len(inp), len(inp[0])
    out_rows, out_cols = len(out), len(out[0])

    # Check for separator column (value 5) -> intersection task
    has_sep = any(
        all(inp[r][c] == 5 for r in range(in_rows))
        for c in range(in_cols)
    )
    if has_sep:
        return "intersection"

    # Check for self-tiling: NxN -> (N*N)x(N*N)
    if in_rows == in_cols and out_rows == in_rows * in_rows and out_cols == in_cols * in_cols:
        return "self_tiling"

    # Check for alternating reflection tiling: 2x2 -> 6x6
    if in_rows == 2 and in_cols == 2 and out_rows == 6 and out_cols == 6:
        return "alt_reflection"

    # Check for pattern continuation: narrow grid, 1->2 color change
    if in_cols <= 3 and out_cols == in_cols and out_rows > in_rows:
        # Check if all non-zero values in input are 1 and in output are 2
        in_vals = {v for row in inp for v in row if v != 0}
        out_vals = {v for row in out for v in row if v != 0}
        if in_vals == {1} and out_vals == {2}:
            return "pattern_continuation"

    # Check for rectangle borders (value 2 forming rectangles) -> fill by size
    border_val = 2
    has_rect_border = False
    for row in inp:
        contiguous = 0
        for v in row:
            if v == border_val:
                contiguous += 1
            else:
                contiguous = 0
            if contiguous >= 3:
                has_rect_border = True
                break
        if has_rect_border:
            break
    if has_rect_border:
        # Check if output fills interior with new colors
        out_vals = {v for row in out for v in row}
        in_vals = {v for row in inp for v in row}
        new_colors = out_vals - in_vals
        if new_colors and new_colors <= {3, 4, 8}:
            return "rect_fill_by_size"

    # Check for enclosed region filling (boundary color 3, fill color 4)
    in_colors = {v for row in inp for v in row if v != 0}
    out_colors = {v for row in out for v in row if v != 0}
    if 3 in in_colors and 4 in out_colors and 4 not in in_colors:
        return "fill_enclosed"

    return "unknown"


def solve_self_tiling(task):
    """Self-tiling: NxN -> (N*N)x(N*N). Each non-zero cell copies input."""
    results = []
    for test in task["test"]:
        ti = test["input"]
        n = len(ti)
        out = [[0] * (n * n) for _ in range(n * n)]
        for r in range(n):
            for c in range(n):
                if ti[r][c] != 0:
                    for dr in range(n):
                        for dc in range(n):
                            out[r * n + dr][c * n + dc] = ti[dr][dc]
        results.append(out)
    return results


def solve_alt_reflection(task):
    """Alternating reflection tiling: 2x2 -> 6x6 with row-block horizontal flip."""
    results = []
    for test in task["test"]:
        ti = test["input"]
        out = [[0] * 6 for _ in range(6)]
        for br in range(3):
            for bc in range(3):
                for r in range(2):
                    for c in range(2):
                        if br % 2 == 0:
                            out[br * 2 + r][bc * 2 + c] = ti[r][c]
                        else:
                            out[br * 2 + r][bc * 2 + c] = ti[r][1 - c]
        results.append(out)
    return results


def solve_intersection(task):
    """Grid intersection: two halves split by column of 5s. Output=2 where both=1."""
    results = []
    for test in task["test"]:
        ti = test["input"]
        rows = len(ti)
        cols = len(ti[0])
        sep = -1
        for c in range(cols):
            if all(ti[r][c] == 5 for r in range(rows)):
                sep = c
                break
        left = [row[:sep] for row in ti]
        right = [row[sep + 1:] for row in ti]
        w = len(left[0])
        out = [[0] * w for _ in range(rows)]
        for r in range(rows):
            for c in range(w):
                if left[r][c] == 1 and right[r][c] == 1:
                    out[r][c] = 2
        results.append(out)
    return results


def solve_fill_enclosed(task):
    """Fill enclosed regions: 0-cells unreachable from boundary via 4-connectivity -> 4."""
    results = []
    for test in task["test"]:
        ti = test["input"]
        rows = len(ti)
        cols = len(ti[0])
        out = [row[:] for row in ti]

        visited = [[False] * cols for _ in range(rows)]
        queue = deque()
        for r in range(rows):
            for c in range(cols):
                if (r == 0 or r == rows - 1 or c == 0 or c == cols - 1) and ti[r][c] == 0:
                    queue.append((r, c))
                    visited[r][c] = True

        while queue:
            r, c = queue.popleft()
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and not visited[nr][nc] and ti[nr][nc] == 0:
                    visited[nr][nc] = True
                    queue.append((nr, nc))

        for r in range(rows):
            for c in range(cols):
                if ti[r][c] == 0 and not visited[r][c]:
                    out[r][c] = 4

        results.append(out)
    return results


def solve_pattern_continuation(task):
    """Pattern continuation: detect period, extend to 1.5x rows, change 1->2."""
    results = []
    for test in task["test"]:
        ti = test["input"]
        rows = len(ti)
        cols = len(ti[0])

        # Detect smallest period
        period = rows
        for p in range(1, rows + 1):
            valid = True
            for r in range(p, rows):
                if ti[r] != ti[r % p]:
                    valid = False
                    break
            if valid:
                period = p
                break

        target_rows = rows + rows // 2
        out = [[0] * cols for _ in range(target_rows)]
        for r in range(target_rows):
            for c in range(cols):
                val = ti[r % period][c]
                out[r][c] = 2 if val == 1 else val

        results.append(out)
    return results


def solve_rect_fill_by_size(task):
    """Rectangle fill by size: 2-bordered rectangles, fill interior by area->color mapping."""
    # Learn size->color mapping from training
    size_to_color = {}
    for example in task["train"]:
        inp = example["input"]
        out = example["output"]
        rows = len(inp)
        cols = len(inp[0])

        visited = [[False] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                if inp[r][c] == 2 and not visited[r][c]:
                    queue = deque([(r, c)])
                    visited[r][c] = True
                    cells = [(r, c)]
                    while queue:
                        cr, cc = queue.popleft()
                        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nr, nc = cr + dr, cc + dc
                            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr][nc] and inp[nr][nc] == 2:
                                visited[nr][nc] = True
                                queue.append((nr, nc))
                                cells.append((nr, nc))

                    min_r = min(cr for cr, cc in cells)
                    max_r = max(cr for cr, cc in cells)
                    min_c = min(cc for cr, cc in cells)
                    max_c = max(cc for cr, cc in cells)

                    int_h = max_r - min_r - 1
                    int_w = max_c - min_c - 1

                    if int_h < 1 or int_w < 1:
                        continue

                    # Verify complete rectangle border
                    cell_set = set(cells)
                    is_border = True
                    for br in range(min_r, max_r + 1):
                        for bc in range(min_c, max_c + 1):
                            on_edge = (br == min_r or br == max_r or bc == min_c or bc == max_c)
                            if on_edge and (br, bc) not in cell_set:
                                is_border = False
                                break
                        if not is_border:
                            break
                    if not is_border:
                        continue

                    # Find fill color from output
                    fill_color = None
                    for ir in range(min_r + 1, max_r):
                        for ic in range(min_c + 1, max_c):
                            if out[ir][ic] != 2 and out[ir][ic] != 0:
                                fill_color = out[ir][ic]
                                break
                        if fill_color is not None:
                            break

                    if fill_color is not None:
                        area = int_h * int_w
                        size_to_color[area] = fill_color

    # Apply to test inputs
    results = []
    for test in task["test"]:
        ti = test["input"]
        rows = len(ti)
        cols = len(ti[0])
        out = [row[:] for row in ti]

        visited = [[False] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                if ti[r][c] == 2 and not visited[r][c]:
                    queue = deque([(r, c)])
                    visited[r][c] = True
                    cells = [(r, c)]
                    while queue:
                        cr, cc = queue.popleft()
                        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nr, nc = cr + dr, cc + dc
                            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr][nc] and ti[nr][nc] == 2:
                                visited[nr][nc] = True
                                queue.append((nr, nc))
                                cells.append((nr, nc))

                    min_r = min(cr for cr, cc in cells)
                    max_r = max(cr for cr, cc in cells)
                    min_c = min(cc for cr, cc in cells)
                    max_c = max(cc for cr, cc in cells)

                    int_h = max_r - min_r - 1
                    int_w = max_c - min_c - 1

                    if int_h < 1 or int_w < 1:
                        continue

                    cell_set = set(cells)
                    is_border = True
                    for br in range(min_r, max_r + 1):
                        for bc in range(min_c, max_c + 1):
                            on_edge = (br == min_r or br == max_r or bc == min_c or bc == max_c)
                            if on_edge and (br, bc) not in cell_set:
                                is_border = False
                                break
                        if not is_border:
                            break
                    if not is_border:
                        continue

                    area = int_h * int_w
                    fill_color = size_to_color.get(area, 4)
                    for ir in range(min_r + 1, max_r):
                        for ic in range(min_c + 1, max_c):
                            if out[ir][ic] == 0:
                                out[ir][ic] = fill_color

        results.append(out)
    return results


SOLVER_MAP = {
    "self_tiling": solve_self_tiling,
    "alt_reflection": solve_alt_reflection,
    "intersection": solve_intersection,
    "fill_enclosed": solve_fill_enclosed,
    "pattern_continuation": solve_pattern_continuation,
    "rect_fill_by_size": solve_rect_fill_by_size,
}


def verify_against_training(task, solver_fn):
    """Verify solver produces correct output for all training examples."""
    # Build a fake task with training inputs as test inputs
    fake_task = {"train": task["train"], "test": [{"input": ex["input"]} for ex in task["train"]]}
    outputs = solver_fn(fake_task)
    for i, (actual, expected) in enumerate(zip(outputs, [ex["output"] for ex in task["train"]])):
        if actual != expected:
            return False, i
    return True, -1


def main():
    os.makedirs("/app/outputs", exist_ok=True)
    task_dir = "/app/tasks"

    for filename in sorted(os.listdir(task_dir)):
        if not filename.endswith(".json"):
            continue
        task_id = filename[:-5]
        task = load_task(os.path.join(task_dir, filename))

        task_type = classify_task(task)
        if task_type == "unknown":
            print(f"WARN: Could not classify {task_id}")
            continue

        solver_fn = SOLVER_MAP[task_type]

        # Verify against training data
        ok, fail_idx = verify_against_training(task, solver_fn)
        if not ok:
            print(f"WARN: Solver for {task_id} ({task_type}) failed on training example {fail_idx}")
            continue

        # Solve test inputs
        outputs = solver_fn(task)
        result = {"test_outputs": outputs}
        out_path = os.path.join("/app/outputs", f"{task_id}.json")
        with open(out_path, "w") as f:
            json.dump(result, f)
        print(f"Solved {task_id} (type={task_type})")


if __name__ == "__main__":
    main()
