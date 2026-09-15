#!/usr/bin/env python3
"""
Tests for gravity source location recovery pipeline.

Generates fresh synthetic gravity data (different sources from the development
data), runs the agent's pipeline, and verifies source recovery accuracy.
"""

import csv
import math
import os
import random
import subprocess

import numpy as np
import pytest

G = 6.674e-11  # gravitational constant

# ── Test source configuration (different from development data) ──────────
TEST_SOURCES = [
    # (easting_m, northing_m, upward_m, mass_kg)
    (20000.0, -25000.0, -7000.0, 4e13),
    (-30000.0, 20000.0, -4500.0, 1.5e13),
    (5000.0, 10000.0, -10000.0, 2e14),
    (-20000.0, -35000.0, -5500.0, 3e13),
]
TEST_REGIONAL = (1.5, 2e-5, 1e-5)  # a0 + a1*e + a2*n
TEST_NOISE_STD = 0.05  # mGal
TEST_SEED = 98765

# ── Tolerance configuration ─────────────────────────────────────────────
HORIZ_TOL = 8000.0   # metres
DEPTH_TOL = 8000.0   # metres
MIN_RECOVERED = 3    # must match at least 3 of 4 true sources
MAX_SOURCES = 10     # prevent trivially large output


# ── Helpers ──────────────────────────────────────────────────────────────

def _generate_test_gravity():
    """Generate synthetic gravity data from point masses."""
    random.seed(TEST_SEED)
    x_min, x_max = -50000, 50000
    y_min, y_max = -50000, 50000
    spacing = 1000

    eastings = list(range(x_min, x_max + 1, spacing))
    northings = list(range(y_min, y_max + 1, spacing))

    rows = []
    for n in northings:
        for e in eastings:
            gz = 0.0
            for e0, n0, u0, mass in TEST_SOURCES:
                dx = e - e0
                dy = n - n0
                dz = -u0  # obs at z=0, source at u0 < 0
                r = math.sqrt(dx * dx + dy * dy + dz * dz)
                gz += G * mass * dz / (r * r * r)
            gz *= 1e5  # to mGal
            a0, a1, a2 = TEST_REGIONAL
            gz += a0 + a1 * e + a2 * n
            gz += random.gauss(0, TEST_NOISE_STD)
            rows.append((float(e), float(n), gz))

    metadata = {
        "region": [x_min, x_max, y_min, y_max],
        "spacing": spacing,
        "grid_shape": [len(northings), len(eastings)],
    }
    return rows, metadata


def _write_data_files(rows, metadata):
    """Write test data in the same TOML+CSV format as the development data."""
    os.makedirs("/app/data", exist_ok=True)
    os.makedirs("/app/results", exist_ok=True)

    # Clean up any pre-existing data files
    for fname in os.listdir("/app/data"):
        fpath = os.path.join("/app/data", fname)
        if os.path.isfile(fpath):
            os.remove(fpath)

    # Write gravity CSV
    with open("/app/data/gravity_data.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["easting", "northing", "g_z"])
        for e, n, gz in rows:
            w.writerow([f"{e:.1f}", f"{n:.1f}", f"{gz:.6f}"])

    # Write TOML survey config (same structure as development data)
    region = metadata["region"]
    shape = metadata["grid_shape"]
    toml_str = """[survey]
region = [{r0}, {r1}, {r2}, {r3}]
grid_spacing_m = {spacing}
n_eastings = {ne}
n_northings = {nn}

[instrument]
type = "relative_gravimeter"
measurement = "vertical_gravitational_acceleration"
units = "mGal"
drift_corrected = true

[processing]
tide_corrected = true
terrain_correction = "not_applied"
regional_field_removed = false
""".format(
        r0=region[0], r1=region[1], r2=region[2], r3=region[3],
        spacing=metadata["spacing"],
        ne=shape[1], nn=shape[0],
    )
    with open("/app/data/survey_config.toml", "w") as f:
        f.write(toml_str)


def _read_sources_csv(path):
    sources = []
    with open(path) as f:
        for row in csv.DictReader(f):
            sources.append(
                {
                    "easting": float(row["easting"]),
                    "northing": float(row["northing"]),
                    "upward": float(row["upward"]),
                }
            )
    return sources


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pipeline_result():
    """Generate fresh test data and run the agent's pipeline once."""
    rows, metadata = _generate_test_gravity()
    _write_data_files(rows, metadata)

    results_path = "/app/results/sources.csv"
    if os.path.exists(results_path):
        os.remove(results_path)

    try:
        result = subprocess.run(
            ["python3", "/app/pipeline.py"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Pipeline timed out after 300 seconds")
    except FileNotFoundError:
        pytest.fail("/app/pipeline.py not found")

    return result


# ── Tests ────────────────────────────────────────────────────────────────

def test_pipeline_script_exists():
    assert os.path.isfile("/app/pipeline.py"), "/app/pipeline.py not found"


def test_pipeline_exits_successfully(pipeline_result):
    assert pipeline_result.returncode == 0, (
        f"Pipeline exited with code {pipeline_result.returncode}.\n"
        f"STDERR (last 2000 chars):\n{pipeline_result.stderr[-2000:]}"
    )


def test_results_file_created(pipeline_result):
    assert os.path.isfile("/app/results/sources.csv"), (
        "Results file /app/results/sources.csv not found after pipeline run"
    )


def test_results_have_correct_columns(pipeline_result):
    sources = _read_sources_csv("/app/results/sources.csv")
    assert len(sources) > 0, "No sources in results file"
    for s in sources:
        assert "easting" in s and "northing" in s and "upward" in s


def test_reasonable_source_count(pipeline_result):
    sources = _read_sources_csv("/app/results/sources.csv")
    assert len(sources) >= MIN_RECOVERED, (
        f"Too few sources recovered: {len(sources)} < {MIN_RECOVERED}"
    )
    assert len(sources) <= MAX_SOURCES, (
        f"Too many sources recovered: {len(sources)} > {MAX_SOURCES}"
    )


def test_all_sources_below_surface(pipeline_result):
    for s in _read_sources_csv("/app/results/sources.csv"):
        assert s["upward"] < 0, (
            f"Source at upward={s['upward']:.0f} is above the surface"
        )


def test_sources_in_study_area(pipeline_result):
    for s in _read_sources_csv("/app/results/sources.csv"):
        assert -60000 <= s["easting"] <= 60000, (
            f"Easting {s['easting']:.0f} outside study area"
        )
        assert -60000 <= s["northing"] <= 60000, (
            f"Northing {s['northing']:.0f} outside study area"
        )
        assert -30000 <= s["upward"] < 0, (
            f"Depth {s['upward']:.0f} unreasonable"
        )


def test_source_locations_recovered(pipeline_result):
    """Each true source must be matched by a recovered source within tolerance."""
    recovered = _read_sources_csv("/app/results/sources.csv")

    matched = 0
    details = []
    for i, (e0, n0, u0, _) in enumerate(TEST_SOURCES):
        best_h = float("inf")
        best_v = float("inf")
        for r in recovered:
            h = math.sqrt((r["easting"] - e0) ** 2 + (r["northing"] - n0) ** 2)
            v = abs(r["upward"] - u0)
            if h < best_h:
                best_h, best_v = h, v
        hit = best_h <= HORIZ_TOL and best_v <= DEPTH_TOL
        matched += int(hit)
        tag = "MATCH" if hit else "MISS"
        details.append(
            f"  Source {i+1} ({e0:.0f}, {n0:.0f}, {u0:.0f}): "
            f"{tag}  closest hdist={best_h:.0f}m  vdist={best_v:.0f}m"
        )

    detail_str = "\n".join(details)
    assert matched >= MIN_RECOVERED, (
        f"Only {matched}/{len(TEST_SOURCES)} true sources recovered "
        f"(need {MIN_RECOVERED}).\n{detail_str}"
    )
