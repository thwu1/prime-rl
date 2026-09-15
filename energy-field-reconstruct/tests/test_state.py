"""
Tests for energy field reconstruction.

Generates random energy field instances with known ground-truth parameters,
creates partial observations (fog of war), runs the solver, and verifies
reconstruction accuracy and model selection.
"""


import json
import math
import os
import subprocess

import numpy as np
import pytest

MAP_SIZE = 24
SEEDS = [303, 271, 42]


def compute_node_contribution_np(tile_coords, node_x, node_y, fn_type, a, b, c):
    """Vectorized computation of a single node's contribution to multiple tiles."""
    dx = tile_coords[:, 0] - node_x
    dy = tile_coords[:, 1] - node_y
    dist = np.sqrt(dx ** 2 + dy ** 2)
    if fn_type == 0:
        return np.sin(dist * a + b) * c
    else:
        return (a / (dist + 1) + b) * c


def generate_energy_field(seed):
    """Generate a random energy field with known ground truth.

    Returns dict with ground_truth_field, ground_truth_nodes,
    n_independent, observed_tiles, and visibility_pct.
    """
    rng = np.random.RandomState(seed)

    # Number of independent nodes (1-3)
    n_independent = int(rng.randint(1, 4))

    # Generate node positions with separation and center-avoidance constraints
    nodes = []
    positions = []

    for _ in range(n_independent):
        placed = False
        for _attempt in range(200):
            x = int(rng.randint(2, 22))
            y = int(rng.randint(2, 22))

            # Must not be too close to map center
            if abs(x - 11.5) < 3 and abs(y - 11.5) < 3:
                continue

            # Must not be too close to own mirror
            mx, my = 23 - x, 23 - y
            if abs(x - mx) + abs(y - my) < 4:
                continue

            # Must not be too close to existing nodes or their mirrors
            too_close = False
            for px, py in positions:
                if abs(x - px) + abs(y - py) < 5:
                    too_close = True
                    break
                pmx, pmy = 23 - px, 23 - py
                if abs(x - pmx) + abs(y - pmy) < 5:
                    too_close = True
                    break
            if too_close:
                continue

            placed = True
            break

        assert placed, f"Failed to place node {len(positions)} with seed {seed}"
        positions.append((x, y))

        fn_type = int(rng.randint(0, 2))

        if fn_type == 0:
            # Sinusoidal: moderate frequency, wide amplitude
            a_mag = float(rng.uniform(0.25, 0.9))
            a = round(float(rng.choice([-1, 1])) * a_mag, 4)
            b = round(float(rng.uniform(-1.5, 1.5)), 4)
            c = round(float(rng.uniform(2.5, 5.5)), 4)
        else:
            # Rational decay: strong distance-dependent peak
            a_mag = float(rng.uniform(2.0, 5.0))
            a = round(float(rng.choice([-1, 1])) * a_mag, 4)
            b = round(float(rng.uniform(-0.3, 0.3)), 4)
            c = round(float(rng.uniform(1.0, 3.0)), 4)

        # Independent node
        nodes.append({
            "pos": [x, y],
            "fn_type": fn_type,
            "params": [a, b, c],
        })
        # Mirror node (180° rotation about center)
        nodes.append({
            "pos": [23 - x, 23 - y],
            "fn_type": fn_type,
            "params": [a, b, c],
        })

    # Compute energy field
    all_coords = np.array(
        [[x, y] for x in range(MAP_SIZE) for y in range(MAP_SIZE)],
        dtype=np.float64,
    )

    raw_field = np.zeros(MAP_SIZE * MAP_SIZE)
    for node in nodes:
        nx, ny = node["pos"]
        a, b, c = node["params"]
        raw_field += compute_node_contribution_np(
            all_coords, nx, ny, node["fn_type"], a, b, c
        )

    raw_field = np.clip(raw_field, -20, 20)
    int_field = np.trunc(raw_field).astype(int)
    field_2d = int_field.reshape(MAP_SIZE, MAP_SIZE)

    # Generate visibility mask (fog of war) using sensor-like circular zones
    visibility = np.zeros((MAP_SIZE, MAP_SIZE), dtype=bool)

    n_sensors = int(rng.randint(8, 15))
    for _ in range(n_sensors):
        cx = int(rng.randint(0, MAP_SIZE))
        cy = int(rng.randint(0, MAP_SIZE))
        r = int(rng.randint(2, 6))
        for x in range(max(0, cx - r), min(MAP_SIZE, cx + r + 1)):
            for y in range(max(0, cy - r), min(MAP_SIZE, cy + r + 1)):
                if max(abs(x - cx), abs(y - cy)) <= r:
                    visibility[x, y] = True

    # Ensure at least 55% coverage
    while visibility.sum() < 0.55 * MAP_SIZE * MAP_SIZE:
        cx = int(rng.randint(0, MAP_SIZE))
        cy = int(rng.randint(0, MAP_SIZE))
        r = int(rng.randint(3, 6))
        for x in range(max(0, cx - r), min(MAP_SIZE, cx + r + 1)):
            for y in range(max(0, cy - r), min(MAP_SIZE, cy + r + 1)):
                if max(abs(x - cx), abs(y - cy)) <= r:
                    visibility[x, y] = True

    # Cap at 75% coverage by removing excess visible tiles
    visible_indices = list(zip(*np.where(visibility)))
    if len(visible_indices) > int(0.75 * MAP_SIZE * MAP_SIZE):
        rng.shuffle(visible_indices)
        excess = len(visible_indices) - int(0.75 * MAP_SIZE * MAP_SIZE)
        for i in range(excess):
            vx, vy = visible_indices[i]
            visibility[vx, vy] = False

    # Create observation dict
    observed = {}
    for x in range(MAP_SIZE):
        for y in range(MAP_SIZE):
            if visibility[x, y]:
                observed[f"{x},{y}"] = int(field_2d[x, y])

    return {
        "ground_truth_field": field_2d.tolist(),
        "ground_truth_nodes": nodes,
        "n_independent": n_independent,
        "observed_tiles": observed,
        "visibility_pct": float(visibility.sum()) / (MAP_SIZE * MAP_SIZE),
    }


# ── Caching: run the solver once per seed, reuse across test methods ────────

_solver_cache = {}


def _run_solver(seed):
    """Generate test data, invoke solver, return results dict."""
    if seed in _solver_cache:
        return _solver_cache[seed]

    data = generate_energy_field(seed)

    input_path = f"/app/test_input_{seed}.json"
    output_path = f"/app/test_output_{seed}.json"

    with open(input_path, "w") as f:
        json.dump(
            {"observed_tiles": data["observed_tiles"], "map_size": MAP_SIZE},
            f,
        )

    result = subprocess.run(
        ["python3", "/app/reconstruct.py", input_path, output_path],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        _solver_cache[seed] = {
            "error": f"exit {result.returncode}: {result.stderr[:800]}",
            "ground_truth": data,
            "output": None,
        }
        return _solver_cache[seed]

    if not os.path.exists(output_path):
        _solver_cache[seed] = {
            "error": "Output file not created",
            "ground_truth": data,
            "output": None,
        }
        return _solver_cache[seed]

    with open(output_path) as f:
        output = json.load(f)

    _solver_cache[seed] = {
        "error": None,
        "ground_truth": data,
        "output": output,
    }
    return _solver_cache[seed]


# ── Test class ──────────────────────────────────────────────────────────────


class TestEnergyFieldReconstruction:
    """Verify energy field reconstruction accuracy across multiple instances."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_solver_succeeds(self, seed):
        """Solver must run without errors."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed for seed {seed}: {r['error']}"

    @pytest.mark.parametrize("seed", SEEDS)
    def test_output_shape(self, seed):
        """Output energy_field must be 24x24."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed: {r['error']}"
        field = np.array(r["output"]["energy_field"])
        assert field.shape == (MAP_SIZE, MAP_SIZE), (
            f"Seed {seed}: shape {field.shape}, expected ({MAP_SIZE},{MAP_SIZE})"
        )

    @pytest.mark.parametrize("seed", SEEDS)
    def test_field_rmse(self, seed):
        """RMSE of reconstructed field vs ground truth must be < 2.0."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed: {r['error']}"

        gt = np.array(r["ground_truth"]["ground_truth_field"])
        pred = np.array(r["output"]["energy_field"])
        rmse = float(np.sqrt(np.mean((gt - pred) ** 2)))
        assert rmse < 2.0, f"Seed {seed}: RMSE = {rmse:.4f} (must be < 2.0)"

    @pytest.mark.parametrize("seed", SEEDS)
    def test_tile_accuracy(self, seed):
        """At least 90% of tiles must have absolute error <= 2."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed: {r['error']}"

        gt = np.array(r["ground_truth"]["ground_truth_field"])
        pred = np.array(r["output"]["energy_field"])
        pct = float(np.mean(np.abs(gt - pred) <= 2)) * 100
        assert pct >= 90.0, (
            f"Seed {seed}: {pct:.1f}% tiles within ±2 (must be >= 90%)"
        )

    @pytest.mark.parametrize("seed", SEEDS)
    def test_node_count(self, seed):
        """Number of independent nodes must match ground truth."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed: {r['error']}"

        predicted = r["output"]["n_nodes"]
        expected = r["ground_truth"]["n_independent"]
        assert predicted == expected, (
            f"Seed {seed}: predicted {predicted} nodes, expected {expected}"
        )

    @pytest.mark.parametrize("seed", SEEDS)
    def test_field_range(self, seed):
        """All reconstructed values must be in [-20, 20]."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed: {r['error']}"

        pred = np.array(r["output"]["energy_field"])
        assert np.all(pred >= -20) and np.all(pred <= 20), (
            f"Seed {seed}: values outside [-20, 20]"
        )

    @pytest.mark.parametrize("seed", SEEDS)
    def test_symmetry(self, seed):
        """Reconstructed field should approximately respect 180° rotational symmetry."""
        r = _run_solver(seed)
        assert r["error"] is None, f"Solver failed: {r['error']}"

        pred = np.array(r["output"]["energy_field"])
        rotated = pred[::-1, ::-1]
        pct_sym = float(np.mean(np.abs(pred - rotated) <= 1)) * 100
        assert pct_sym >= 95.0, (
            f"Seed {seed}: {pct_sym:.1f}% tiles symmetric (must be >= 95%)"
        )
