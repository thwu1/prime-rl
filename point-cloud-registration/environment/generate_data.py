#!/usr/bin/env python3
"""Generate point cloud registration scenarios stored in SQLite + TOML. Pure Python."""

import random
import math
import os
import sqlite3


def rotation_matrix(axis, angle_deg):
    """Rodrigues' rotation formula."""
    angle = math.radians(angle_deg)
    norm = math.sqrt(sum(a * a for a in axis))
    ax, ay, az = axis[0] / norm, axis[1] / norm, axis[2] / norm
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    return [
        [t * ax * ax + c, t * ax * ay - s * az, t * ax * az + s * ay],
        [t * ax * ay + s * az, t * ay * ay + c, t * ay * az - s * ax],
        [t * ax * az - s * ay, t * ay * az + s * ax, t * az * az + c],
    ]


def mat_vec(R, v):
    """3x3 matrix times 3-vector."""
    return [sum(R[i][j] * v[j] for j in range(3)) for i in range(3)]


def randn(rng):
    """Standard normal variate via Box-Muller."""
    u1 = rng.random()
    u2 = rng.random()
    while u1 < 1e-12:
        u1 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def generate_scenario(config):
    rng = random.Random(config["seed"])
    n = config["n_points"]
    R = rotation_matrix(config["axis"], config["angle_deg"])
    t = config["translation"]
    sc = config["scale"]
    noise_std = config["noise_std"]
    outlier_ratio = config["outlier_ratio"]
    overlap_ratio = config["overlap_ratio"]

    # Generate source points (anisotropic Gaussian for asymmetry)
    source = []
    for _ in range(n):
        x = randn(rng) * 2.3
        y = randn(rng) * 1.4
        z = randn(rng) * 0.9
        source.append([x, y, z])

    n_overlap = int(n * overlap_ratio)

    if overlap_ratio < 1.0:
        indices = list(range(n))
        rng.shuffle(indices)
        overlap_indices = indices[:n_overlap]

        target = []
        for idx in overlap_indices:
            pt = source[idx]
            tr = mat_vec(R, pt)
            tr = [sc * tr[j] + t[j] for j in range(3)]
            if noise_std > 0:
                tr = [tr[j] + randn(rng) * noise_std for j in range(3)]
            target.append(tr)

        # Non-overlapping points far from the main cluster
        n_extra = n - n_overlap
        for _ in range(n_extra):
            pt = [
                randn(rng) * 2.0 + 7.0,
                randn(rng) * 2.0 + 7.0,
                randn(rng) * 2.0 + 7.0,
            ]
            target.append(pt)
    else:
        target = []
        for pt in source:
            tr = mat_vec(R, pt)
            tr = [sc * tr[j] + t[j] for j in range(3)]
            if noise_std > 0:
                tr = [tr[j] + randn(rng) * noise_std for j in range(3)]
            target.append(tr)

    # Add uniform outlier points within expanded bounding box
    n_outliers = int(len(target) * outlier_ratio)
    if n_outliers > 0:
        mn = [min(p[j] for p in target) - 1.5 for j in range(3)]
        mx = [max(p[j] for p in target) + 1.5 for j in range(3)]
        for _ in range(n_outliers):
            target.append([rng.uniform(mn[j], mx[j]) for j in range(3)])

    # Shuffle target to destroy ordering
    rng.shuffle(target)
    return source, target


# Unique, non-round parameters that serve as task DNA
SCENARIOS = [
    {
        "name": "clean_rigid",
        "n_points": 250,
        "axis": [0.2673, 0.5345, 0.8018],
        "angle_deg": 23.7,
        "translation": [0.847, -0.293, 0.518],
        "scale": 1.0,
        "noise_std": 0.0,
        "outlier_ratio": 0.0,
        "overlap_ratio": 1.0,
        "seed": 8347,
    },
    {
        "name": "noisy_scaled",
        "n_points": 350,
        "axis": [0.5774, 0.5774, 0.5774],
        "angle_deg": 41.3,
        "translation": [1.274, 0.619, -0.832],
        "scale": 1.17,
        "noise_std": 0.025,
        "outlier_ratio": 0.0,
        "overlap_ratio": 1.0,
        "seed": 2951,
    },
    {
        "name": "outlier_contaminated",
        "n_points": 400,
        "axis": [0.4472, 0.8944, 0.0],
        "angle_deg": 53.8,
        "translation": [0.416, 0.937, -0.572],
        "scale": 1.34,
        "noise_std": 0.035,
        "outlier_ratio": 0.18,
        "overlap_ratio": 1.0,
        "seed": 6173,
    },
    {
        "name": "partial_overlap",
        "n_points": 500,
        "axis": [0.7071, 0.0, 0.7071],
        "angle_deg": 78.4,
        "translation": [1.863, -0.741, 0.394],
        "scale": 0.82,
        "noise_std": 0.045,
        "outlier_ratio": 0.22,
        "overlap_ratio": 0.60,
        "seed": 4529,
    },
]


def main():
    os.makedirs("/app", exist_ok=True)

    # ── Create SQLite database ──────────────────────────────────────────
    db_path = "/app/scans.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE scans (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            noise_std REAL NOT NULL,
            outlier_ratio REAL NOT NULL,
            overlap_ratio REAL NOT NULL,
            n_source INTEGER NOT NULL,
            n_target INTEGER NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE source_points (
            scan_id INTEGER NOT NULL,
            point_idx INTEGER NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,
            PRIMARY KEY (scan_id, point_idx),
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)

    c.execute("""
        CREATE TABLE target_points (
            scan_id INTEGER NOT NULL,
            point_idx INTEGER NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,
            PRIMARY KEY (scan_id, point_idx),
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)

    c.execute("CREATE INDEX idx_source_scan ON source_points(scan_id)")
    c.execute("CREATE INDEX idx_target_scan ON target_points(scan_id)")

    for i, cfg in enumerate(SCENARIOS):
        name = cfg["name"]
        source, target = generate_scenario(cfg)

        c.execute(
            "INSERT INTO scans (id, name, noise_std, outlier_ratio, overlap_ratio, n_source, n_target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i + 1, name, cfg["noise_std"], cfg["outlier_ratio"],
             cfg["overlap_ratio"], len(source), len(target)),
        )

        for j, pt in enumerate(source):
            c.execute(
                "INSERT INTO source_points (scan_id, point_idx, x, y, z) VALUES (?, ?, ?, ?, ?)",
                (i + 1, j, pt[0], pt[1], pt[2]),
            )

        for j, pt in enumerate(target):
            c.execute(
                "INSERT INTO target_points (scan_id, point_idx, x, y, z) VALUES (?, ?, ?, ?, ?)",
                (i + 1, j, pt[0], pt[1], pt[2]),
            )

        print(f"Stored {name}: {len(source)} source, {len(target)} target points")

    conn.commit()
    conn.close()

    # ── Create TOML pipeline configuration ──────────────────────────────
    toml_content = """\
[pipeline]
input_db = "/app/scans.db"
output_db = "/app/results.db"

[registration]
method = "rigid_probabilistic"
max_iterations = 400
convergence_tol = 1e-9
estimate_scale = true

[registration.bounds]
scale_min = 0.3
scale_max = 3.0

[outlier_weights]
clean_rigid = 0.15
noisy_scaled = 0.30
outlier_contaminated = 0.55
partial_overlap = 0.65
"""
    with open("/app/pipeline.toml", "w") as f:
        f.write(toml_content)

    print("Data generation complete!")
    print(f"Database: {db_path}")
    print(f"Config: /app/pipeline.toml")


if __name__ == "__main__":
    main()
