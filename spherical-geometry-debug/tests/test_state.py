
import subprocess
import json
import math
import pytest


def run_js(expression: str):
    """Execute a JS expression using the compiled library and return the result."""
    script = f"""
    const lib = require('./dist/index');
    const result = {expression};
    console.log(JSON.stringify(result));
    """
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True, text=True, cwd="/app",
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Node.js error (exit {proc.returncode}):\n{proc.stderr}"
        )
    return json.loads(proc.stdout.strip())


def assert_in_delta(actual, expected, delta):
    """Assert that actual is within delta of expected, recursing into arrays."""
    if isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)), f"Expected list, got {type(actual)}"
        assert len(actual) == len(expected), (
            f"Length mismatch: {len(actual)} vs {len(expected)}"
        )
        for a, e in zip(actual, expected):
            assert_in_delta(a, e, delta)
    else:
        assert abs(actual - expected) <= delta, (
            f"{actual} not within {delta} of {expected}"
        )


# ---------------------------------------------------------------------------
# Area tests
# ---------------------------------------------------------------------------

class TestSphericalArea:
    def test_sphere(self):
        result = run_js('lib.sphericalArea({type: "Sphere"})')
        assert_in_delta(result, 4 * math.pi, 1e-5)

    def test_semilune(self):
        result = run_js(
            'lib.sphericalArea({type: "Polygon", '
            'coordinates: [[[0,0],[0,90],[90,0],[0,0]]]})'
        )
        assert_in_delta(result, math.pi / 2, 1e-5)

    def test_lune(self):
        result = run_js(
            'lib.sphericalArea({type: "Polygon", '
            'coordinates: [[[0,0],[0,90],[90,0],[0,-90],[0,0]]]})'
        )
        assert_in_delta(result, math.pi, 1e-5)

    def test_hemisphere_north(self):
        result = run_js(
            'lib.sphericalArea({type: "Polygon", '
            'coordinates: [[[0,0],[-90,0],[180,0],[90,0],[0,0]]]})'
        )
        assert_in_delta(result, 2 * math.pi, 1e-5)

    def test_hemisphere_south(self):
        """South hemisphere has opposite winding — tests negative-area normalization."""
        result = run_js(
            'lib.sphericalArea({type: "Polygon", '
            'coordinates: [[[0,0],[90,0],[180,0],[-90,0],[0,0]]]})'
        )
        assert_in_delta(result, 2 * math.pi, 1e-5)

    def test_hemisphere_east(self):
        result = run_js(
            'lib.sphericalArea({type: "Polygon", '
            'coordinates: [[[0,0],[0,90],[180,0],[0,-90],[0,0]]]})'
        )
        assert_in_delta(result, 2 * math.pi, 1e-5)

    def test_tiny_polygon(self):
        result = run_js(
            'lib.sphericalArea({type: "Polygon", coordinates: [['
            '[-64.66070178517852, 18.33986913231323],'
            '[-64.66079715091509, 18.33994007490749],'
            '[-64.66074946804680, 18.33994007490749],'
            '[-64.66070178517852, 18.33986913231323]'
            ']]})'
        )
        assert abs(result - 4.890516e-13) < 1e-13

    def test_point_has_zero_area(self):
        result = run_js('lib.sphericalArea({type: "Point", coordinates: [0, 0]})')
        assert result == 0

    def test_multipolygon_two_hemispheres(self):
        result = run_js(
            'lib.sphericalArea({type: "MultiPolygon", coordinates: ['
            '[[[0,0],[-90,0],[180,0],[90,0],[0,0]]],'
            '[[[0,0],[90,0],[180,0],[-90,0],[0,0]]]'
            ']})'
        )
        assert_in_delta(result, 4 * math.pi, 1e-5)


# ---------------------------------------------------------------------------
# Centroid tests
# ---------------------------------------------------------------------------

class TestSphericalCentroid:
    def test_point(self):
        result = run_js(
            'lib.sphericalCentroid({type: "Point", coordinates: [0, 0]})'
        )
        assert_in_delta(result, [0, 0], 1e-6)

    def test_point_nonzero(self):
        result = run_js(
            'lib.sphericalCentroid({type: "Point", coordinates: [1, 1]})'
        )
        assert_in_delta(result, [1, 1], 1e-6)

    def test_multipoint_average(self):
        result = run_js(
            'lib.sphericalCentroid({type: "MultiPoint", '
            'coordinates: [[0, 0], [1, 2]]})'
        )
        assert_in_delta(result, [0.499847, 1.000038], 1e-6)

    def test_linestring_meridional(self):
        result = run_js(
            'lib.sphericalCentroid({type: "LineString", '
            'coordinates: [[0, 0], [0, 90]]})'
        )
        assert_in_delta(result, [0, 45], 1e-6)

    def test_linestring_equatorial(self):
        result = run_js(
            'lib.sphericalCentroid({type: "LineString", '
            'coordinates: [[0, 0], [1, 0]]})'
        )
        assert_in_delta(result, [0.5, 0], 1e-6)

    def test_polygon_lune(self):
        """Centroid of a lune — requires correct area-weighted centroid."""
        result = run_js(
            'lib.sphericalCentroid({type: "Polygon", '
            'coordinates: [[[0,-90],[0,0],[0,90],[1,0],[0,-90]]]})'
        )
        assert_in_delta(result, [0.5, 0], 1e-6)

    def test_polygon_square(self):
        result = run_js(
            'lib.sphericalCentroid({type: "Polygon", '
            'coordinates: [[[0,-10],[0,10],[10,10],[10,-10],[0,-10]]]})'
        )
        assert_in_delta(result, [5, 0], 1e-6)

    def test_sphere_ambiguous(self):
        result = run_js(
            'lib.sphericalCentroid({type: "Sphere"})'
        )
        # NaN becomes null in JSON → None in Python
        assert result[0] is None and result[1] is None

    def test_antipodal_points_ambiguous(self):
        result = run_js(
            'lib.sphericalCentroid({type: "MultiPoint", '
            'coordinates: [[0, 0], [180, 0]]})'
        )
        assert result[0] is None and result[1] is None


# ---------------------------------------------------------------------------
# Contains tests
# ---------------------------------------------------------------------------

class TestSphericalContains:
    def test_sphere_contains_any(self):
        result = run_js(
            'lib.sphericalContains({type: "Sphere"}, [0, 0])'
        )
        assert result is True

    def test_point_contains_itself(self):
        result = run_js(
            'lib.sphericalContains({type: "Point", coordinates: [0, 0]}, [0, 0])'
        )
        assert result is True

    def test_point_does_not_contain_other(self):
        result = run_js(
            'lib.sphericalContains({type: "Point", coordinates: [0, 0]}, [0, 1])'
        )
        assert result is False

    def test_polygon_contains_interior(self):
        result = run_js(
            'lib.sphericalContains('
            '{type: "Polygon", coordinates: [['
            '[0,-10],[0,10],[10,10],[10,-10],[0,-10]'
            ']]}, [5, 0])'
        )
        assert result is True

    def test_polygon_excludes_exterior(self):
        result = run_js(
            'lib.sphericalContains('
            '{type: "Polygon", coordinates: [['
            '[0,-10],[0,10],[10,10],[10,-10],[0,-10]'
            ']]}, [20, 0])'
        )
        assert result is False

    def test_south_pole_enclosure_inside(self):
        """Triangle encircling south pole — point near pole should be inside."""
        result = run_js(
            'lib.sphericalContains('
            '{type: "Polygon", coordinates: [['
            '[-60,-80],[60,-80],[180,-80],[-60,-80]'
            ']]}, [0, -85])'
        )
        assert result is True

    def test_south_pole_enclosure_outside(self):
        result = run_js(
            'lib.sphericalContains('
            '{type: "Polygon", coordinates: [['
            '[-60,-80],[60,-80],[180,-80],[-60,-80]'
            ']]}, [0, 0])'
        )
        assert result is False

    def test_north_pole_enclosure(self):
        result = run_js(
            'lib.sphericalContains('
            '{type: "Polygon", coordinates: [['
            '[60,80],[-60,80],[-180,80],[60,80]'
            ']]}, [0, 85])'
        )
        assert result is True

    def test_null_contains_nothing(self):
        result = run_js(
            'lib.sphericalContains(null, [0, 0])'
        )
        assert result is False


# ---------------------------------------------------------------------------
# Distance tests
# ---------------------------------------------------------------------------

class TestSphericalDistance:
    def test_zero_distance(self):
        result = run_js('lib.sphericalDistance([0, 0], [0, 0])')
        assert result == 0

    def test_quarter_sphere(self):
        """0° to 90° along a meridian = π/2 radians."""
        result = run_js('lib.sphericalDistance([0, 0], [0, 90])')
        assert_in_delta(result, math.pi / 2, 1e-6)

    def test_half_sphere(self):
        """Antipodal on equator = π radians."""
        result = run_js('lib.sphericalDistance([0, 0], [180, 0])')
        assert_in_delta(result, math.pi, 1e-6)

    def test_diagonal_differs_from_euclidean(self):
        """Two points at 45°N separated by 90° longitude.
        Great-circle distance = π/3 ≈ 1.0472.
        Euclidean approx would give π/2 ≈ 1.5708.
        """
        result = run_js('lib.sphericalDistance([0, 45], [90, 45])')
        assert_in_delta(result, math.pi / 3, 1e-6)

    def test_small_distance_positive(self):
        result = run_js('lib.sphericalDistance([0, 0], [0, 1e-12])')
        assert result > 0


# ---------------------------------------------------------------------------
# Interpolation tests
# ---------------------------------------------------------------------------

class TestSphericalInterpolate:
    def test_start_point(self):
        result = run_js(
            '(function() {'
            '  const f = lib.sphericalInterpolate([0, 0], [0, 90]);'
            '  return f(0);'
            '})()'
        )
        assert_in_delta(result, [0, 0], 1e-6)

    def test_end_point(self):
        result = run_js(
            '(function() {'
            '  const f = lib.sphericalInterpolate([0, 0], [0, 90]);'
            '  return f(1);'
            '})()'
        )
        assert_in_delta(result, [0, 90], 1e-6)

    def test_midpoint_meridional(self):
        result = run_js(
            '(function() {'
            '  const f = lib.sphericalInterpolate([0, 0], [0, 90]);'
            '  return f(0.5);'
            '})()'
        )
        assert_in_delta(result, [0, 45], 1e-6)

    def test_great_circle_midpoint_at_45(self):
        """Midpoint of (0°,45°N)→(90°,45°N) should be at ~(45°, 54.7356°).
        Linear interpolation would give (45°, 45°) which is wrong.
        """
        result = run_js(
            '(function() {'
            '  const f = lib.sphericalInterpolate([0, 45], [90, 45]);'
            '  return f(0.5);'
            '})()'
        )
        expected_lat = math.degrees(math.asin(math.sqrt(2.0 / 3.0)))
        assert_in_delta(result[0], 45.0, 1e-6)
        assert_in_delta(result[1], expected_lat, 1e-4)

    def test_distance_property(self):
        result = run_js(
            '(function() {'
            '  const f = lib.sphericalInterpolate([0, 0], [0, 90]);'
            '  return f.distance;'
            '})()'
        )
        assert_in_delta(result, math.pi / 2, 1e-6)

    def test_distance_property_diagonal(self):
        result = run_js(
            '(function() {'
            '  const f = lib.sphericalInterpolate([0, 45], [90, 45]);'
            '  return f.distance;'
            '})()'
        )
        assert_in_delta(result, math.pi / 3, 1e-6)
