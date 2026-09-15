#!/usr/bin/env python3
"""
ARC-AGI Pipeline: fetches tasks from REST API, solves each by inferring
transformation rules, submits via API, logs metadata to SQLite, and
generates PPM visualizations for ImageMagick conversion.
"""

import json
import os
import sqlite3
import urllib.request
from collections import deque

API_BASE = "http://localhost:8080"
DB_PATH = "/app/pipeline.db"
VIZ_DIR = "/app/visualizations"

ARC_PALETTE = {
    0: (0, 0, 0),
    1: (0, 116, 217),
    2: (255, 65, 54),
    3: (46, 204, 64),
    4: (255, 220, 0),
    5: (170, 170, 170),
    6: (240, 18, 190),
    7: (255, 133, 27),
    8: (127, 219, 255),
    9: (135, 12, 37),
}


def api_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def api_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


# ========== ARC Task Classification ==========

def classify_task(task):
    train = task["train"]
    ex0 = train[0]
    inp, out = ex0["input"], ex0["output"]
    in_rows, in_cols = len(inp), len(inp[0])
    out_rows, out_cols = len(out), len(out[0])

    # Separator column of 5s -> intersection
    has_sep = any(
        all(inp[r][c] == 5 for r in range(in_rows)) for c in range(in_cols)
    )
    if has_sep:
        return "intersection"

    # NxN -> (N*N)x(N*N) -> self-tiling
    if (
        in_rows == in_cols
        and out_rows == in_rows * in_rows
        and out_cols == in_cols * in_cols
    ):
        return "self_tiling"

    # 2x2 -> 6x6 -> alternating reflection
    if in_rows == 2 and in_cols == 2 and out_rows == 6 and out_cols == 6:
        return "alternating_reflection"

    # Narrow grid, 1->2 color change -> pattern continuation
    if in_cols <= 3 and out_cols == in_cols and out_rows > in_rows:
        in_vals = {v for row in inp for v in row if v != 0}
        out_vals = {v for row in out for v in row if v != 0}
        if in_vals == {1} and out_vals == {2}:
            return "pattern_continuation"

    # Border value 2 forming rectangles -> fill by area
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
        out_vals = {v for row in out for v in row}
        in_vals = {v for row in inp for v in row}
        new_colors = out_vals - in_vals
        if new_colors and new_colors <= {3, 4, 8}:
            return "rectangle_fill_by_area"

    # Boundary 3, fill 4 -> flood fill enclosed
    in_colors = {v for row in inp for v in row if v != 0}
    out_colors = {v for row in out for v in row if v != 0}
    if 3 in in_colors and 4 in out_colors and 4 not in in_colors:
        return "flood_fill_enclosed"

    return "unknown"


# ========== Solvers ==========

def solve_self_tiling(task):
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


def solve_alternating_reflection(task):
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
    results = []
    for test in task["test"]:
        ti = test["input"]
        rows = len(ti)
        cols = len(ti[0])
        sep = next(
            c for c in range(cols) if all(ti[r][c] == 5 for r in range(rows))
        )
        left = [row[:sep] for row in ti]
        right = [row[sep + 1 :] for row in ti]
        w = len(left[0])
        out = [[0] * w for _ in range(rows)]
        for r in range(rows):
            for c in range(w):
                if left[r][c] == 1 and right[r][c] == 1:
                    out[r][c] = 2
        results.append(out)
    return results


def solve_flood_fill_enclosed(task):
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
                if (
                    0 <= nr < rows
                    and 0 <= nc < cols
                    and not visited[nr][nc]
                    and ti[nr][nc] == 0
                ):
                    visited[nr][nc] = True
                    queue.append((nr, nc))
        for r in range(rows):
            for c in range(cols):
                if ti[r][c] == 0 and not visited[r][c]:
                    out[r][c] = 4
        results.append(out)
    return results


def solve_pattern_continuation(task):
    results = []
    for test in task["test"]:
        ti = test["input"]
        rows = len(ti)
        cols = len(ti[0])
        period = rows
        for p in range(1, rows + 1):
            if all(ti[r] == ti[r % p] for r in range(p, rows)):
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


def solve_rectangle_fill_by_area(task):
    # Learn area -> fill color mapping from training examples
    size_to_color = {}
    for example in task["train"]:
        inp = example["input"]
        out_grid = example["output"]
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
                            if (
                                0 <= nr < rows
                                and 0 <= nc < cols
                                and not visited[nr][nc]
                                and inp[nr][nc] == 2
                            ):
                                visited[nr][nc] = True
                                queue.append((nr, nc))
                                cells.append((nr, nc))
                    min_r = min(cr for cr, _ in cells)
                    max_r = max(cr for cr, _ in cells)
                    min_c = min(cc for _, cc in cells)
                    max_c = max(cc for _, cc in cells)
                    int_h = max_r - min_r - 1
                    int_w = max_c - min_c - 1
                    if int_h < 1 or int_w < 1:
                        continue
                    cell_set = set(cells)
                    is_border = True
                    for br in range(min_r, max_r + 1):
                        for bc in range(min_c, max_c + 1):
                            on_edge = br == min_r or br == max_r or bc == min_c or bc == max_c
                            if on_edge and (br, bc) not in cell_set:
                                is_border = False
                                break
                        if not is_border:
                            break
                    if not is_border:
                        continue
                    fill_color = None
                    for ir in range(min_r + 1, max_r):
                        for ic in range(min_c + 1, max_c):
                            if out_grid[ir][ic] != 2 and out_grid[ir][ic] != 0:
                                fill_color = out_grid[ir][ic]
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
                            if (
                                0 <= nr < rows
                                and 0 <= nc < cols
                                and not visited[nr][nc]
                                and ti[nr][nc] == 2
                            ):
                                visited[nr][nc] = True
                                queue.append((nr, nc))
                                cells.append((nr, nc))
                    min_r = min(cr for cr, _ in cells)
                    max_r = max(cr for cr, _ in cells)
                    min_c = min(cc for _, cc in cells)
                    max_c = max(cc for _, cc in cells)
                    int_h = max_r - min_r - 1
                    int_w = max_c - min_c - 1
                    if int_h < 1 or int_w < 1:
                        continue
                    cell_set = set(cells)
                    is_border = True
                    for br in range(min_r, max_r + 1):
                        for bc in range(min_c, max_c + 1):
                            on_edge = br == min_r or br == max_r or bc == min_c or bc == max_c
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
    "alternating_reflection": solve_alternating_reflection,
    "intersection": solve_intersection,
    "flood_fill_enclosed": solve_flood_fill_enclosed,
    "pattern_continuation": solve_pattern_continuation,
    "rectangle_fill_by_area": solve_rectangle_fill_by_area,
}


def generate_ppm(grid, filepath):
    """Generate a PPM (P3) image file from a grid for ImageMagick conversion."""
    rows = len(grid)
    cols = len(grid[0])
    cell_size = 20
    width = cols * cell_size
    height = rows * cell_size

    with open(filepath, "w") as f:
        f.write(f"P3\n{width} {height}\n255\n")
        for r in range(rows):
            for pixel_row in range(cell_size):
                line_parts = []
                for c in range(cols):
                    cr, cg, cb = ARC_PALETTE[grid[r][c]]
                    pixel = f"{cr} {cg} {cb}"
                    line_parts.extend([pixel] * cell_size)
                f.write(" ".join(line_parts) + "\n")


def main():
    os.makedirs(VIZ_DIR, exist_ok=True)

    # Fetch task list from API
    task_list = api_get("/api/tasks")
    print(f"Found {len(task_list['tasks'])} tasks via API")

    solved = []

    for task_info in task_list["tasks"]:
        task_id = task_info["task_id"]

        # Fetch task data from API
        resp = api_get(f"/api/tasks/{task_id}")
        task_data = resp["data"]

        # Classify and solve
        task_type = classify_task(task_data)
        if task_type == "unknown":
            print(f"WARN: Cannot classify {task_id}")
            continue

        solver_fn = SOLVER_MAP[task_type]
        outputs = solver_fn(task_data)

        # Submit via API
        result = api_post(f"/api/tasks/{task_id}/submit", {"test_outputs": outputs})
        print(f"Submitted {task_id}: {result['status']}")

        # Compute metadata
        test_input = task_data["test"][0]["input"]
        test_output = outputs[0]
        num_colors = len({v for row in test_output for v in row})

        solved.append(
            {
                "task_id": task_id,
                "input_rows": len(test_input),
                "input_cols": len(test_input[0]),
                "output_rows": len(test_output),
                "output_cols": len(test_output[0]),
                "num_colors": num_colors,
                "transformation_type": task_type,
            }
        )

        # Generate PPM visualization for each test output
        for i, grid in enumerate(outputs):
            ppm_path = os.path.join(VIZ_DIR, f"{task_id}_test_{i}.ppm")
            generate_ppm(grid, ppm_path)

        print(f"Solved {task_id} (type={task_type})")

    # Populate solve_log table via sqlite3
    conn = sqlite3.connect(DB_PATH)
    for entry in solved:
        conn.execute(
            "INSERT OR REPLACE INTO solve_log "
            "(task_id, input_rows, input_cols, output_rows, output_cols, "
            "num_colors, transformation_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry["task_id"],
                entry["input_rows"],
                entry["input_cols"],
                entry["output_rows"],
                entry["output_cols"],
                entry["num_colors"],
                entry["transformation_type"],
            ),
        )
    conn.commit()
    conn.close()
    print(f"Logged {len(solved)} entries to solve_log")


if __name__ == "__main__":
    main()
