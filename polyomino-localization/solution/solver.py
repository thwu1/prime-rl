#!/usr/bin/env python3

"""
Solver for Polyomino Localization Pipeline.

Reads multi-format input:
  - /app/config.toml (TOML): grid parameters
  - /app/shapes/ (CSV): polyomino cell definitions
  - /app/data.db (SQLite): measurement data

Uses coordinate descent + simulated annealing optimization.
Writes results to /app/results.db (SQLite).
"""
import tomllib
import csv
import sqlite3
import os
import math
import random


def read_config(path="/app/config.toml"):
    with open(path, "rb") as f:
        return tomllib.load(f)


def read_shapes(shapes_dir, num_instances):
    all_shapes = []
    for i in range(num_instances):
        inst_dir = os.path.join(shapes_dir, f"instance_{i}")
        shapes = []
        j = 0
        while True:
            csv_path = os.path.join(inst_dir, f"poly_{j}.csv")
            if not os.path.exists(csv_path):
                break
            cells = []
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cells.append((int(row["row"]), int(row["col"])))
            shapes.append(cells)
            j += 1
        all_shapes.append(shapes)
    return all_shapes


def read_measurements(db_path, num_instances):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    all_meas = []
    for i in range(num_instances):
        cur.execute(
            "SELECT region_r1, region_c1, region_r2, region_c2, noisy_value "
            "FROM measurements WHERE instance_id = ? ORDER BY meas_id",
            (i,)
        )
        all_meas.append(cur.fetchall())
    conn.close()
    return all_meas


def solve_instance(grid_size, polyominoes, measurements):
    num_polys = len(polyominoes)
    num_meas = len(measurements)

    if num_polys == 0:
        return [[0] * grid_size for _ in range(grid_size)]

    all_positions = []
    for poly in polyominoes:
        max_r = max(r for r, c in poly)
        max_c = max(c for r, c in poly)
        all_positions.append(
            [(dr, dc) for dr in range(grid_size - max_r)
             for dc in range(grid_size - max_c)]
        )

    regions = [(m[0], m[1], m[2], m[3]) for m in measurements]
    targets = [m[4] for m in measurements]
    weights = [
        1.0 / max((r2 - r1) * (c2 - c1), 1)
        for r1, c1, r2, c2 in regions
    ]

    placed_cells = []
    for i, poly in enumerate(polyominoes):
        pc = []
        for dr, dc in all_positions[i]:
            pc.append([(r + dr, c + dc) for r, c in poly])
        placed_cells.append(pc)

    contributions = []
    for i in range(num_polys):
        poly_c = []
        for idx in range(len(all_positions[i])):
            cells = placed_cells[i][idx]
            contribs = [
                sum(1 for pr, pc_v in cells
                    if r1 <= pr < r2 and c1 <= pc_v < c2)
                for r1, c1, r2, c2 in regions
            ]
            poly_c.append(contribs)
        contributions.append(poly_c)

    rng = random.Random(42)
    best_overall_error = float('inf')
    best_overall_indices = None
    num_restarts = 100

    for restart in range(num_restarts):
        cur_indices = []
        occupied = set()

        if restart == 0:
            preds = [0.0] * num_meas
            for i in range(num_polys):
                best_idx = -1
                best_err = float('inf')
                for idx in range(len(all_positions[i])):
                    if any(cell in occupied for cell in placed_cells[i][idx]):
                        continue
                    c_i = contributions[i][idx]
                    err = sum(
                        (preds[m] + c_i[m] - targets[m]) ** 2 * weights[m]
                        for m in range(num_meas)
                    )
                    if err < best_err:
                        best_err = err
                        best_idx = idx
                if best_idx == -1:
                    best_idx = 0
                cur_indices.append(best_idx)
                for cell in placed_cells[i][best_idx]:
                    occupied.add(cell)
                c_i = contributions[i][best_idx]
                for m in range(num_meas):
                    preds[m] += c_i[m]
        else:
            for i in range(num_polys):
                valid = [
                    idx for idx in range(len(all_positions[i]))
                    if not any(cell in occupied
                               for cell in placed_cells[i][idx])
                ]
                if not valid:
                    valid = list(range(len(all_positions[i])))
                idx = valid[rng.randint(0, len(valid) - 1)]
                cur_indices.append(idx)
                for cell in placed_cells[i][idx]:
                    occupied.add(cell)

        preds = [0.0] * num_meas
        for i in range(num_polys):
            c_i = contributions[i][cur_indices[i]]
            for m in range(num_meas):
                preds[m] += c_i[m]

        for _ in range(30):
            changed = False
            for i in range(num_polys):
                old_idx = cur_indices[i]
                old_c = contributions[i][old_idx]
                for cell in placed_cells[i][old_idx]:
                    occupied.discard(cell)

                best_idx = old_idx
                best_err = float('inf')
                for idx in range(len(all_positions[i])):
                    if any(cell in occupied for cell in placed_cells[i][idx]):
                        continue
                    c_i = contributions[i][idx]
                    err = sum(
                        (preds[m] - old_c[m] + c_i[m] - targets[m]) ** 2
                        * weights[m]
                        for m in range(num_meas)
                    )
                    if err < best_err:
                        best_err = err
                        best_idx = idx

                cur_indices[i] = best_idx
                new_c = contributions[i][best_idx]
                for cell in placed_cells[i][best_idx]:
                    occupied.add(cell)
                for m in range(num_meas):
                    preds[m] += new_c[m] - old_c[m]
                if best_idx != old_idx:
                    changed = True

            if not changed:
                break

        error = sum(
            (preds[m] - targets[m]) ** 2 * weights[m]
            for m in range(num_meas)
        )
        if error < best_overall_error:
            best_overall_error = error
            best_overall_indices = list(cur_indices)

    # Simulated annealing refinement
    cur_indices = list(best_overall_indices)
    occupied = set()
    for i in range(num_polys):
        for cell in placed_cells[i][cur_indices[i]]:
            occupied.add(cell)
    preds = [0.0] * num_meas
    for i in range(num_polys):
        c_i = contributions[i][cur_indices[i]]
        for m in range(num_meas):
            preds[m] += c_i[m]
    cur_error = sum(
        (preds[m] - targets[m]) ** 2 * weights[m]
        for m in range(num_meas)
    )
    best_sa_error = cur_error
    best_sa_indices = list(cur_indices)

    T_start = 2.0
    T_end = 0.0001
    sa_iters = 300000

    for it in range(sa_iters):
        T = T_start * (T_end / T_start) ** (it / sa_iters)
        pi = rng.randint(0, num_polys - 1)
        new_idx = rng.randint(0, len(all_positions[pi]) - 1)
        old_idx = cur_indices[pi]
        if new_idx == old_idx:
            continue

        old_cells_sa = placed_cells[pi][old_idx]
        for cell in old_cells_sa:
            occupied.discard(cell)

        new_cells_sa = placed_cells[pi][new_idx]
        if any(cell in occupied for cell in new_cells_sa):
            for cell in old_cells_sa:
                occupied.add(cell)
            continue

        old_c = contributions[pi][old_idx]
        new_c = contributions[pi][new_idx]
        new_error = sum(
            (preds[m] - old_c[m] + new_c[m] - targets[m]) ** 2 * weights[m]
            for m in range(num_meas)
        )
        delta = new_error - cur_error
        if delta <= 0 or rng.random() < math.exp(-delta / max(T, 1e-10)):
            cur_indices[pi] = new_idx
            for cell in new_cells_sa:
                occupied.add(cell)
            for m in range(num_meas):
                preds[m] += new_c[m] - old_c[m]
            cur_error = new_error
            if cur_error < best_sa_error:
                best_sa_error = cur_error
                best_sa_indices = list(cur_indices)
        else:
            for cell in old_cells_sa:
                occupied.add(cell)

    if best_sa_error < best_overall_error:
        best_overall_indices = best_sa_indices

    grid = [[0] * grid_size for _ in range(grid_size)]
    for i in range(num_polys):
        for r, c in placed_cells[i][best_overall_indices[i]]:
            grid[r][c] = 1
    return grid


def write_results(results, grid_size):
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE solutions (
        instance_id INTEGER NOT NULL,
        row INTEGER NOT NULL,
        col INTEGER NOT NULL,
        value INTEGER NOT NULL CHECK(value IN (0, 1)),
        PRIMARY KEY (instance_id, row, col)
    )""")
    for i, grid in enumerate(results):
        rows = []
        for r in range(grid_size):
            for c in range(grid_size):
                rows.append((i, r, c, grid[r][c]))
        cur.executemany("INSERT INTO solutions VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def main():
    config = read_config()
    grid_size = config["grid"]["size"]
    num_instances = config["instances"]["count"]

    all_shapes = read_shapes("/app/shapes", num_instances)
    all_meas = read_measurements("/app/data.db", num_instances)

    results = []
    for i in range(num_instances):
        print(f"Solving instance {i}...", flush=True)
        grid = solve_instance(grid_size, all_shapes[i], all_meas[i])
        results.append(grid)
        print(f"  Done.", flush=True)

    write_results(results, grid_size)
    print("Results written to /app/results.db", flush=True)


if __name__ == "__main__":
    main()
