
"""
Tests for the gyroid lattice infill generator.

Validates the result JSON, manifold properties, volume fraction accuracy,
function correctness, and performs independent cross-verification.
"""

import json
import math
import os
import sys
import importlib.util

import pytest


SPEC_PATH = "/app/spec.json"
RESULT_PATH = "/app/result.json"


@pytest.fixture(scope="session")
def task_spec():
    with open(SPEC_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def output():
    if not os.path.isfile(RESULT_PATH):
        pytest.fail(f"{RESULT_PATH} was not created by the script")
    with open(RESULT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def module():
    script = "/app/lattice_generator.py"
    if not os.path.isfile(script):
        pytest.fail(f"{script} does not exist")
    mod_spec = importlib.util.spec_from_file_location("lattice_generator", script)
    mod = importlib.util.module_from_spec(mod_spec)
    try:
        mod_spec.loader.exec_module(mod)
    except Exception as e:
        pytest.fail(f"Failed to import {script}: {e}")
    return mod


# =========================================================
# Schema and type validation
# =========================================================

def test_result_exists():
    assert os.path.isfile(RESULT_PATH), f"{RESULT_PATH} not found"


def test_result_schema(output):
    required = [
        "iso_thickness", "volume_fraction", "solid_volume",
        "bounding_volume", "surface_area", "genus", "status",
        "num_vert", "num_tri",
    ]
    for key in required:
        assert key in output, f"Missing required key: {key}"


def test_result_types(output):
    assert isinstance(output["iso_thickness"], (int, float))
    assert isinstance(output["volume_fraction"], (int, float))
    assert isinstance(output["solid_volume"], (int, float))
    assert isinstance(output["bounding_volume"], (int, float))
    assert isinstance(output["surface_area"], (int, float))
    assert isinstance(output["genus"], int)
    assert isinstance(output["status"], str)
    assert isinstance(output["num_vert"], int)
    assert isinstance(output["num_tri"], int)


# =========================================================
# Manifold validity
# =========================================================

def test_manifold_status(output):
    status = output["status"]
    assert "NoError" in status or "no_error" in status.lower(), (
        f"Manifold status is '{status}', expected NoError"
    )


def test_mesh_nonempty(output):
    assert output["num_vert"] > 0, "Mesh has no vertices"
    assert output["num_tri"] > 0, "Mesh has no triangles"


def test_mesh_closed(output):
    F = output["num_tri"]
    assert F % 2 == 0, (
        f"num_tri = {F} is odd; a closed triangle mesh must have even "
        f"triangle count (since E = 3F/2 must be an integer)"
    )


# =========================================================
# Volume fraction correctness
# =========================================================

def test_volume_fraction_within_tolerance(output, task_spec):
    target = task_spec["target_volume_fraction"]
    tolerance = task_spec["volume_fraction_tolerance"]
    vf = output["volume_fraction"]
    assert abs(vf - target) <= tolerance, (
        f"Volume fraction {vf:.4f} not within {tolerance} of target {target}"
    )


def test_volume_fraction_range(output):
    vf = output["volume_fraction"]
    assert 0 < vf < 1, f"Volume fraction {vf} must be in (0, 1)"


# =========================================================
# iso_thickness validation
# =========================================================

def test_iso_thickness_positive(output):
    assert output["iso_thickness"] > 0, (
        f"iso_thickness must be positive, got {output['iso_thickness']}"
    )


def test_iso_thickness_range(output):
    t = output["iso_thickness"]
    assert 0 < t < 1.5, (
        f"iso_thickness {t} not in valid range (0, 1.5); "
        f"gyroid SDF range is approximately [-1.5, 1.5]"
    )


# =========================================================
# Topological properties
# =========================================================

def test_genus_positive(output):
    assert output["genus"] > 0, (
        f"Genus must be > 0 for a gyroid lattice, got {output['genus']}"
    )


def test_euler_identity(output):
    V = output["num_vert"]
    F = output["num_tri"]
    E = 3 * F // 2
    chi_mesh = V - E + F
    chi_genus = 2 * (1 - output["genus"])
    assert chi_mesh == chi_genus, (
        f"Euler identity failed: V-E+F = {V}-{E}+{F} = {chi_mesh}, "
        f"but 2(1-g) = {chi_genus}"
    )


# =========================================================
# Geometric consistency
# =========================================================

def test_volumes_consistent(output):
    solid = output["solid_volume"]
    bound = output["bounding_volume"]
    vf = output["volume_fraction"]
    expected_vf = solid / bound
    assert abs(vf - expected_vf) < 0.001, (
        f"Volume fraction {vf} inconsistent with "
        f"solid_volume/bounding_volume = {expected_vf:.6f}"
    )


def test_surface_area_positive(output):
    assert output["surface_area"] > 0, "Surface area must be positive"


def test_bounding_volume_positive(output):
    assert output["bounding_volume"] > 0, "Bounding volume must be positive"


def test_solid_volume_positive(output):
    assert output["solid_volume"] > 0, "Solid volume must be positive"


def test_solid_smaller_than_bounding(output):
    assert output["solid_volume"] < output["bounding_volume"], (
        f"Solid volume {output['solid_volume']:.2f} must be less than "
        f"bounding volume {output['bounding_volume']:.2f}"
    )


# =========================================================
# Module interface checks
# =========================================================

def test_module_has_functions(module):
    required_funcs = [
        "gyroid_sdf", "build_bounding_shape", "build_lattice",
        "find_iso_thickness", "generate_lattice",
    ]
    for func in required_funcs:
        assert hasattr(module, func), f"Module missing function: {func}"
        assert callable(getattr(module, func)), f"{func} is not callable"


# =========================================================
# Gyroid SDF mathematical properties
# =========================================================

def test_gyroid_sdf_at_origin(module):
    val = module.gyroid_sdf(0.0, 0.0, 0.0)
    assert abs(val) < 1e-10, (
        f"gyroid_sdf(0,0,0) = {val}, expected 0.0"
    )


def test_gyroid_sdf_cyclic_symmetry(module):
    """Gyroid has cyclic (x->y->z->x) symmetry."""
    v1 = module.gyroid_sdf(1.0, 0.5, 0.3)
    v2 = module.gyroid_sdf(0.5, 0.3, 1.0)
    v3 = module.gyroid_sdf(0.3, 1.0, 0.5)
    assert abs(v1 - v2) < 1e-10 and abs(v2 - v3) < 1e-10, (
        f"Cyclic symmetry failed: f(1,0.5,0.3)={v1}, "
        f"f(0.5,0.3,1)={v2}, f(0.3,1,0.5)={v3}"
    )


def test_gyroid_sdf_periodicity(module):
    """Gyroid has period 2*pi in each axis."""
    import random
    random.seed(42)
    x, y, z = random.random(), random.random(), random.random()
    v1 = module.gyroid_sdf(x, y, z)
    v2 = module.gyroid_sdf(x + 2 * math.pi, y, z)
    v3 = module.gyroid_sdf(x, y + 2 * math.pi, z)
    v4 = module.gyroid_sdf(x, y, z + 2 * math.pi)
    assert abs(v1 - v2) < 1e-10, f"Not periodic in x: {v1} vs {v2}"
    assert abs(v1 - v3) < 1e-10, f"Not periodic in y: {v1} vs {v3}"
    assert abs(v1 - v4) < 1e-10, f"Not periodic in z: {v1} vs {v4}"


def test_gyroid_sdf_bounded(module):
    """Gyroid SDF is bounded in [-1.5, 1.5]."""
    import random
    random.seed(123)
    for _ in range(1000):
        x = random.uniform(-10, 10)
        y = random.uniform(-10, 10)
        z = random.uniform(-10, 10)
        val = module.gyroid_sdf(x, y, z)
        assert -1.6 < val < 1.6, (
            f"gyroid_sdf({x},{y},{z}) = {val} outside expected range"
        )


# =========================================================
# Bounding shape validation
# =========================================================

def test_bounding_shape_valid(module):
    rd = module.build_bounding_shape(10.0)
    assert rd.volume() > 0, "Bounding shape has zero volume"
    status = str(rd.status())
    assert "NoError" in status or "no_error" in status.lower(), (
        f"Bounding shape has bad status: {status}"
    )


def test_bounding_shape_volume_scaling(module):
    """Volume scales as size^3."""
    v1 = module.build_bounding_shape(10.0).volume()
    v2 = module.build_bounding_shape(20.0).volume()
    ratio = v2 / v1
    expected_ratio = 8.0  # (20/10)^3
    assert abs(ratio - expected_ratio) / expected_ratio < 0.01, (
        f"Volume ratio {ratio:.4f} does not match expected {expected_ratio}"
    )


def test_bounding_volume_matches_construction(output, module, task_spec):
    """Reported bounding_volume matches independently constructed shape."""
    rd = module.build_bounding_shape(task_spec["bounding_size"])
    rd_vol = rd.volume()
    reported = output["bounding_volume"]
    rel_err = abs(rd_vol - reported) / reported
    assert rel_err < 0.01, (
        f"Bounding volume mismatch: reported={reported:.2f}, "
        f"constructed={rd_vol:.2f}"
    )


# =========================================================
# Independent cross-verification (anti-cheat)
# =========================================================

def test_build_lattice_produces_valid_manifold(output, module, task_spec):
    """Independently construct lattice with reported iso_thickness."""
    iso_t = output["iso_thickness"]
    size = task_spec["bounding_size"]
    n = task_spec["num_periods"]
    m = task_spec["mesh_segments_per_period"]

    lattice = module.build_lattice(iso_t, size, n, m)

    status = str(lattice.status())
    assert "NoError" in status or "no_error" in status.lower(), (
        f"Independently built lattice has bad status: {status}"
    )
    assert lattice.volume() > 0, "Independently built lattice has zero volume"


def test_independent_volume_fraction(output, module, task_spec):
    """Verify reported volume fraction by independent construction."""
    iso_t = output["iso_thickness"]
    size = task_spec["bounding_size"]
    n = task_spec["num_periods"]
    m = task_spec["mesh_segments_per_period"]

    lattice = module.build_lattice(iso_t, size, n, m)
    rd = module.build_bounding_shape(size)
    vf = lattice.volume() / rd.volume()

    assert abs(vf - output["volume_fraction"]) < 0.02, (
        f"Independent VF {vf:.4f} differs from reported "
        f"{output['volume_fraction']:.4f}"
    )


def test_volume_fraction_monotonic(module, task_spec):
    """Increasing iso_thickness must increase volume fraction."""
    size = task_spec["bounding_size"]
    n = task_spec["num_periods"]

    rd = module.build_bounding_shape(size)
    rd_vol = rd.volume()

    # Use coarser mesh for speed
    lat1 = module.build_lattice(0.15, size, n, 8)
    lat2 = module.build_lattice(0.6, size, n, 8)

    vf1 = lat1.volume() / rd_vol
    vf2 = lat2.volume() / rd_vol

    assert vf2 > vf1, (
        f"Monotonicity violated: VF at t=0.6 ({vf2:.4f}) should be greater "
        f"than VF at t=0.15 ({vf1:.4f})"
    )
