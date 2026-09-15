"""
Test suite for SDF Rendering Pipeline.

"""

import json
import math
import os
import pytest


RESULTS_PATH = "/app/results.json"

# Pre-computed reference values from the authoritative SDF engine
REFERENCE = {
    # Distance queries (id -> expected_value)
    1: -0.61149354,
    2: 0.00988095,
    3: 1.41969698,
    4: -0.15703125,
    5: 0.15008377,
    6: 0.22081037,
    7: 0.00837777,
    8: -0.13118326,
    9: -0.11584625,
    10: -0.02578125,
    11: 2.10277942,
    12: -0.05413103,
    13: -0.091125,
    14: -0.5,
    15: 0.06277857,
    16: 0.05677164,
    17: 0.36808454,
    18: -0.04,
    19: -0.21458954,
    20: -0.06328125,
    21: -0.2175476,
    22: -0.22812654,
    23: -0.2,
    24: -0.09807828,
    25: 0.01131828,
}

REFERENCE_NORMALS = {
    # Normal queries (id -> [nx, ny, nz])
    26: [0.89114356, -0.45372145, 0.0],
    27: [0.0, 1.0, 0.0],
    28: [0.0, 0.15016616, 0.98866077],
    29: [0.51923454, 0.85463179, 0.0],
    30: [0.0, 1.0, 0.0],
    31: [0.99402605, -0.10914305, 0.0],
    32: [0.0, -1.0, 0.0],
    33: [0.0, 0.4237582, -0.90577535],
    34: [0.41703245, 0.82697791, 0.37708285],
    35: [0.0, 0.97760493, -0.21044856],
    36: [-0.95808151, 0.24172313, 0.15378474],
    37: [0.0, 5.3e-07, -1.0],
    38: [0.0, -1.0, 0.0],
    39: [0.31759395, -0.79411956, 0.51817778],
    40: [0.0, -1.0, 0.0],
}

REFERENCE_RAYCASTS = {
    # Ray cast queries (id -> {"hit": bool, ...})
    41: {"hit": True, "t": 3.698883, "point": [1.301117, 0.0, 0.0],
         "normal": [0.536894, -0.84365, 0.0]},
    42: {"hit": True, "t": 2.66, "point": [0.0, 2.34, 0.0],
         "normal": [0.0, 1.0, 0.0]},
    43: {"hit": True, "t": 4.013564, "point": [0.0, 0.0, 0.986436],
         "normal": [0.0, 0.192524, 0.981292]},
    44: {"hit": True, "t": 3.0, "point": [-2.0, -1.5, 0.0],
         "normal": [-1.0, 0.0, 0.0]},
    45: {"hit": True, "t": 1.342969, "point": [0.0, -1.657031, 0.0],
         "normal": [0.0, -1.0, 0.0]},
    46: {"hit": True, "t": 2.46, "point": [0.0, 1.8, 0.54],
         "normal": [0.0, 0.0, 1.0]},
    47: {"hit": False},
    48: {"hit": True, "t": 0.666615, "point": [1.403761, 0.298119, 0.0],
         "normal": [0.929831, 0.367988, 0.0]},
    49: {"hit": True, "t": 1.470405, "point": [0.0, 0.0, -1.529595],
         "normal": [0.0, 0.008083, -0.999967]},
    50: {"hit": True, "t": 1.0, "point": [2.0, -1.35, 1.5],
         "normal": [0.707107, 0.707107, 0.0]},
}

REFERENCE_CLASSIFY = {
    # Classify queries (id -> "inside"/"outside"/"surface")
    51: "inside",
    52: "outside",
    53: "inside",
    54: "inside",
    55: "outside",
    56: "inside",
    57: "outside",
    58: "inside",
    59: "inside",
    60: "inside",
}

# Tolerances
DIST_TOL = 5e-4
NORMAL_TOL = 5e-2
RAY_T_TOL = 2e-2
RAY_POINT_TOL = 2e-2
RAY_NORMAL_TOL = 0.1


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The engine must write query results to this path."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "results.json must contain a JSON array"
    return {r["id"]: r for r in data}


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), (
            f"Results file not found at {RESULTS_PATH}"
        )

    def test_results_has_all_queries(self, results):
        expected_ids = set(range(1, 61))
        actual_ids = set(results.keys())
        missing = expected_ids - actual_ids
        assert not missing, f"Missing query IDs in results: {sorted(missing)}"


class TestDistanceQueries:
    """Test SDF distance evaluation at 25 query points."""

    @pytest.mark.parametrize("qid", sorted(REFERENCE.keys()))
    def test_distance(self, results, qid):
        assert qid in results, f"Missing result for query {qid}"
        r = results[qid]
        assert r["type"] == "distance", f"Query {qid}: expected type 'distance', got '{r['type']}'"
        expected = REFERENCE[qid]
        actual = r["value"]
        assert abs(actual - expected) < DIST_TOL, (
            f"Query {qid}: distance mismatch. "
            f"Expected {expected:.6f}, got {actual:.6f}, "
            f"error {abs(actual-expected):.6f} > tolerance {DIST_TOL}"
        )


class TestNormalQueries:
    """Test surface normal computation at 15 query points."""

    @pytest.mark.parametrize("qid", sorted(REFERENCE_NORMALS.keys()))
    def test_normal(self, results, qid):
        assert qid in results, f"Missing result for query {qid}"
        r = results[qid]
        assert r["type"] == "normal", f"Query {qid}: expected type 'normal'"
        expected = REFERENCE_NORMALS[qid]
        actual = r["value"]
        assert isinstance(actual, list) and len(actual) == 3, (
            f"Query {qid}: normal must be a 3-element list"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert abs(a - e) < NORMAL_TOL, (
                f"Query {qid}: normal component {i} mismatch. "
                f"Expected {e:.6f}, got {a:.6f}, "
                f"error {abs(a-e):.6f} > tolerance {NORMAL_TOL}"
            )

        # Verify approximately unit length
        length = math.sqrt(sum(x * x for x in actual))
        assert abs(length - 1.0) < 0.05, (
            f"Query {qid}: normal not unit length ({length:.4f})"
        )


class TestRayCastQueries:
    """Test ray casting for 10 queries."""

    @pytest.mark.parametrize("qid", sorted(REFERENCE_RAYCASTS.keys()))
    def test_ray_cast(self, results, qid):
        assert qid in results, f"Missing result for query {qid}"
        r = results[qid]
        assert r["type"] == "ray_cast", f"Query {qid}: expected type 'ray_cast'"
        expected = REFERENCE_RAYCASTS[qid]
        actual = r["value"]

        assert actual["hit"] == expected["hit"], (
            f"Query {qid}: hit mismatch. Expected {expected['hit']}, got {actual['hit']}"
        )

        if not expected["hit"]:
            return

        # Check t
        assert abs(actual["t"] - expected["t"]) < RAY_T_TOL, (
            f"Query {qid}: t mismatch. "
            f"Expected {expected['t']:.6f}, got {actual['t']:.6f}, "
            f"error {abs(actual['t']-expected['t']):.6f}"
        )

        # Check hit point
        for i in range(3):
            assert abs(actual["point"][i] - expected["point"][i]) < RAY_POINT_TOL, (
                f"Query {qid}: point[{i}] mismatch. "
                f"Expected {expected['point'][i]:.6f}, got {actual['point'][i]:.6f}"
            )

        # Check hit normal
        for i in range(3):
            assert abs(actual["normal"][i] - expected["normal"][i]) < RAY_NORMAL_TOL, (
                f"Query {qid}: normal[{i}] mismatch. "
                f"Expected {expected['normal'][i]:.6f}, got {actual['normal'][i]:.6f}"
            )


class TestClassifyQueries:
    """Test inside/outside classification at 10 query points."""

    @pytest.mark.parametrize("qid", sorted(REFERENCE_CLASSIFY.keys()))
    def test_classify(self, results, qid):
        assert qid in results, f"Missing result for query {qid}"
        r = results[qid]
        assert r["type"] == "classify", f"Query {qid}: expected type 'classify'"
        expected = REFERENCE_CLASSIFY[qid]
        actual = r["value"]
        assert actual == expected, (
            f"Query {qid}: classification mismatch. "
            f"Expected '{expected}', got '{actual}'"
        )


class TestConsistency:
    """Cross-check consistency between query types."""

    def test_all_results_present(self, results):
        """Verify all 60 results are present with correct types."""
        type_counts = {"distance": 0, "normal": 0, "ray_cast": 0, "classify": 0}
        for r in results.values():
            if r["type"] in type_counts:
                type_counts[r["type"]] += 1
        assert type_counts["distance"] == 25, f"Expected 25 distance results, got {type_counts['distance']}"
        assert type_counts["normal"] == 15, f"Expected 15 normal results, got {type_counts['normal']}"
        assert type_counts["ray_cast"] == 10, f"Expected 10 ray_cast results, got {type_counts['ray_cast']}"
        assert type_counts["classify"] == 10, f"Expected 10 classify results, got {type_counts['classify']}"


# ===== Render Output Tests =====

def _parse_pgm(path):
    """Parse a P2 ASCII PGM file, returning (width, height, maxval, pixels)."""
    with open(path) as f:
        content = f.read()
    # Strip comments (lines starting with #, or inline # in header)
    lines = content.split('\n')
    clean_parts = []
    for line in lines:
        idx = line.find('#')
        if idx >= 0:
            line = line[:idx]
        clean_parts.append(line)
    tokens = ' '.join(clean_parts).split()
    magic = tokens[0]
    width = int(tokens[1])
    height = int(tokens[2])
    maxval = int(tokens[3])
    pixels = [int(t) for t in tokens[4:]]
    return magic, width, height, maxval, pixels


class TestRenderPGM:
    """Verify the depth-map PGM render."""

    def test_pgm_exists(self):
        assert os.path.exists("/app/render.pgm"), "render.pgm not found"

    def test_pgm_format(self):
        magic, width, height, maxval, pixels = _parse_pgm("/app/render.pgm")
        assert magic == "P2", f"PGM magic must be P2, got {magic}"
        assert width == 256, f"Width must be 256, got {width}"
        assert height == 256, f"Height must be 256, got {height}"
        assert maxval == 255, f"Max value must be 255, got {maxval}"

    def test_pgm_pixel_count(self):
        _, width, height, _, pixels = _parse_pgm("/app/render.pgm")
        expected = width * height
        assert len(pixels) == expected, (
            f"Expected {expected} pixels, got {len(pixels)}"
        )

    def test_pgm_has_variation(self):
        """The rendered image should not be flat (all same value)."""
        _, _, _, _, pixels = _parse_pgm("/app/render.pgm")
        unique_vals = set(pixels)
        assert len(unique_vals) > 5, (
            f"Rendered image has only {len(unique_vals)} distinct values "
            f"(expected a non-trivial depth map)"
        )

    def test_pgm_center_vs_corner(self):
        """Center pixels should show geometry (low depth); corner should be background."""
        _, width, height, _, pixels = _parse_pgm("/app/render.pgm")
        # Center pixel (128, 128) — camera looks at scene center
        center_idx = 128 * width + 128
        center = pixels[center_idx]
        # Top-left corner (0, 0) — should miss geometry
        corner = pixels[0]
        assert center < 200, (
            f"Center pixel should show geometry (got {center}, expected < 200)"
        )
        assert corner > 200, (
            f"Corner pixel should be near background (got {corner}, expected > 200)"
        )
        assert center < corner, (
            f"Center ({center}) should be closer (lower) than corner ({corner})"
        )

    def test_pgm_pixel_range(self):
        """All pixel values must be in [0, 255]."""
        _, _, _, _, pixels = _parse_pgm("/app/render.pgm")
        assert all(0 <= p <= 255 for p in pixels), "Pixel values out of [0, 255] range"


class TestRenderPNG:
    """Verify the PNG conversion of the depth map."""

    def test_png_exists(self):
        assert os.path.exists("/app/render.png"), "render.png not found"

    def test_png_valid(self):
        with open("/app/render.png", "rb") as f:
            magic = f.read(8)
        # PNG magic bytes
        assert magic[:4] == b'\x89PNG', "render.png is not a valid PNG file"


# ===== Cross-Section Tests =====

def _read_cross_section(path):
    """Read cross_section.dat, return (xs, vals) as lists of floats."""
    xs, vals = [], []
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                xs.append(float(parts[0]))
                vals.append(float(parts[1]))
    return xs, vals


def _interpolate(xs, vals, target):
    """Linear interpolation to find value at target x."""
    # Check exact endpoints
    if abs(xs[0] - target) < 1e-6:
        return vals[0]
    if abs(xs[-1] - target) < 1e-6:
        return vals[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= target <= xs[i + 1]:
            if abs(xs[i + 1] - xs[i]) < 1e-12:
                return vals[i]
            t = (target - xs[i]) / (xs[i + 1] - xs[i])
            return vals[i] + t * (vals[i + 1] - vals[i])
    return None


class TestCrossSectionData:
    """Verify cross-section data file."""

    def test_dat_exists(self):
        assert os.path.exists("/app/cross_section.dat"), "cross_section.dat not found"

    def test_dat_sample_count(self):
        xs, vals = _read_cross_section("/app/cross_section.dat")
        assert len(xs) == 500, f"Expected 500 samples, got {len(xs)}"

    def test_dat_x_range(self):
        xs, _ = _read_cross_section("/app/cross_section.dat")
        assert abs(xs[0] - (-3.0)) < 0.02, f"First x should be -3.0, got {xs[0]}"
        assert abs(xs[-1] - 3.0) < 0.02, f"Last x should be 3.0, got {xs[-1]}"

    def test_dat_monotonic_x(self):
        xs, _ = _read_cross_section("/app/cross_section.dat")
        for i in range(1, len(xs)):
            assert xs[i] > xs[i - 1], (
                f"x values must be strictly increasing: x[{i-1}]={xs[i-1]}, x[{i}]={xs[i]}"
            )

    def test_dat_spot_check_origin(self):
        """SDF at (0, 0, 0) should match distance query 1."""
        xs, vals = _read_cross_section("/app/cross_section.dat")
        val_0 = _interpolate(xs, vals, 0.0)
        assert val_0 is not None, "Could not interpolate to x=0"
        expected = -0.61149354  # REFERENCE[1]
        assert abs(val_0 - expected) < 0.01, (
            f"Cross-section at x=0: expected {expected:.6f}, got {val_0:.6f}"
        )

    def test_dat_spot_check_far(self):
        """SDF at (3, 0, 0) should match distance query 3."""
        xs, vals = _read_cross_section("/app/cross_section.dat")
        val_3 = _interpolate(xs, vals, 3.0)
        assert val_3 is not None, "Could not interpolate to x=3.0"
        expected = 1.41969698  # REFERENCE[3]
        assert abs(val_3 - expected) < 0.01, (
            f"Cross-section at x=3: expected {expected:.6f}, got {val_3:.6f}"
        )

    def test_dat_spot_check_negative(self):
        """SDF at (-1, 0, 0) should match distance query 12."""
        xs, vals = _read_cross_section("/app/cross_section.dat")
        val_neg1 = _interpolate(xs, vals, -1.0)
        assert val_neg1 is not None, "Could not interpolate to x=-1.0"
        expected = -0.05413103  # REFERENCE[12]
        assert abs(val_neg1 - expected) < 0.01, (
            f"Cross-section at x=-1: expected {expected:.6f}, got {val_neg1:.6f}"
        )


class TestCrossSectionPlot:
    """Verify cross-section plot PNG."""

    def test_plot_exists(self):
        assert os.path.exists("/app/cross_section.png"), "cross_section.png not found"

    def test_plot_valid_png(self):
        with open("/app/cross_section.png", "rb") as f:
            magic = f.read(8)
        assert magic[:4] == b'\x89PNG', "cross_section.png is not a valid PNG file"

    def test_plot_not_empty(self):
        size = os.path.getsize("/app/cross_section.png")
        assert size > 1000, (
            f"cross_section.png is suspiciously small ({size} bytes)"
        )
