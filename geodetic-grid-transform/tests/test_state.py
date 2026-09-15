
"""
Tests for the geodetic datum transformation engine.

Generates synthetic binary GTX grid files with known biquadratic surfaces,
runs the Java transformation engine, and compares outputs against an
independent Python reference implementation.
"""

import struct
import math
import subprocess
import os
import pytest

# ---------------------------------------------------------------------------
# Grid parameters
# ---------------------------------------------------------------------------
LAT_MIN = 39.0
LON_MIN = 279.0
DLAT = 0.25
DLON = 0.20
NROWS = 9
NCOLS = 11
GRID_DIR = "/app/data/grids"

# ---------------------------------------------------------------------------
# Grid value formulas (biquadratic surfaces in row/col indices)
# These are exactly representable by biquadratic Lagrange interpolation.
# ---------------------------------------------------------------------------

def ab_lattrn(r, c):
    return 0.500 + 0.040 * r + 0.020 * c + 0.003 * r * c - 0.002 * r * r + 0.001 * c * c

def ab_lontrn(r, c):
    return -0.300 + 0.032 * r - 0.024 * c + 0.005 * r * c + 0.001 * r * r - 0.001 * c * c

def ab_laterr(r, c):
    return 0.0100

def ab_lonerr(r, c):
    return 0.0150

def bc_lattrn(r, c):
    return 0.200 + 0.015 * r + 0.028 * c - 0.002 * r * c + 0.001 * r * r + 0.002 * c * c

def bc_lontrn(r, c):
    return 0.100 + 0.020 * r + 0.036 * c + 0.004 * r * c - 0.001 * r * r + 0.001 * c * c

def bc_laterr(r, c):
    return 0.0050

def bc_lonerr(r, c):
    return 0.0080

# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------

def generate_grid_values(func):
    values = []
    for r in range(NROWS):
        for c in range(NCOLS):
            values.append(func(r, c))
    return values


def write_binary_grid(filename, values):
    """Write a binary GTX grid file (big-endian, Java DataOutputStream format)."""
    with open(filename, 'wb') as f:
        f.write(struct.pack('>d', LAT_MIN))
        f.write(struct.pack('>d', LON_MIN))
        f.write(struct.pack('>d', DLAT))
        f.write(struct.pack('>d', DLON))
        f.write(struct.pack('>i', NROWS))
        f.write(struct.pack('>i', NCOLS))
        for v in values:
            f.write(struct.pack('>f', v))

# ---------------------------------------------------------------------------
# Reference biquadratic interpolation
# ---------------------------------------------------------------------------

def lagrange_basis(index, t):
    """Lagrange basis polynomial for nodes at 0, 1, 2."""
    if index == 0:
        return (t - 1) * (t - 2) / 2.0
    elif index == 1:
        return -t * (t - 2)
    elif index == 2:
        return t * (t - 1) / 2.0
    raise ValueError(f"Invalid index {index}")


def biquad_interp(block, x, y):
    """Biquadratic (Lagrange) interpolation on a 3x3 block."""
    result = 0.0
    for i in range(3):
        rv = 0.0
        for j in range(3):
            rv += block[i * 3 + j] * lagrange_basis(j, y)
        result += rv * lagrange_basis(i, x)
    return result


def interp_grid(grid_values, lat, lon):
    """Interpolate a value from a grid at the given lat/lon (positive-East)."""
    frac_row = (lat - LAT_MIN) / DLAT
    frac_col = (lon - LON_MIN) / DLON
    base_row = int(math.floor(frac_row)) - 1
    base_col = int(math.floor(frac_col)) - 1
    block = []
    for i in range(3):
        for j in range(3):
            block.append(grid_values[(base_row + i) * NCOLS + (base_col + j)])
    x = frac_row - base_row
    y = frac_col - base_col
    return biquad_interp(block, x, y)

# ---------------------------------------------------------------------------
# Reference transformation
# ---------------------------------------------------------------------------

GRID_FUNCS = {
    ('DATUM_A', 'DATUM_B'): {
        'lattrn': ab_lattrn, 'lontrn': ab_lontrn,
        'laterr': ab_laterr, 'lonerr': ab_lonerr,
    },
    ('DATUM_B', 'DATUM_C'): {
        'lattrn': bc_lattrn, 'lontrn': bc_lontrn,
        'laterr': bc_laterr, 'lonerr': bc_lonerr,
    },
}

# Cache generated grid values
_grid_cache = {}

def get_grid_values(key, func):
    if key not in _grid_cache:
        _grid_cache[key] = generate_grid_values(func)
    return _grid_cache[key]


def transform_ref(lat, lon_east, src, dest):
    """Reference implementation of chained datum transformation."""
    datums = ['DATUM_A', 'DATUM_B', 'DATUM_C']
    src_idx = datums.index(src)
    dest_idx = datums.index(dest)

    cur_lat, cur_lon = lat, lon_east
    sig_lat_sq = 0.0
    sig_lon_sq = 0.0

    if dest_idx > src_idx:
        for i in range(src_idx, dest_idx):
            from_d, to_d = datums[i], datums[i + 1]
            g = GRID_FUNCS[(from_d, to_d)]
            lat_shift = interp_grid(get_grid_values(f'{from_d}_{to_d}_lattrn', g['lattrn']), cur_lat, cur_lon)
            lon_shift = interp_grid(get_grid_values(f'{from_d}_{to_d}_lontrn', g['lontrn']), cur_lat, cur_lon)
            lat_err = interp_grid(get_grid_values(f'{from_d}_{to_d}_laterr', g['laterr']), cur_lat, cur_lon)
            lon_err = interp_grid(get_grid_values(f'{from_d}_{to_d}_lonerr', g['lonerr']), cur_lat, cur_lon)
            cur_lat += lat_shift / 3600.0
            cur_lon += lon_shift / 3600.0
            sig_lat_sq += lat_err ** 2
            sig_lon_sq += lon_err ** 2
    else:
        for i in range(src_idx, dest_idx, -1):
            from_d, to_d = datums[i - 1], datums[i]
            g = GRID_FUNCS[(from_d, to_d)]
            lat_shift = interp_grid(get_grid_values(f'{from_d}_{to_d}_lattrn', g['lattrn']), cur_lat, cur_lon)
            lon_shift = interp_grid(get_grid_values(f'{from_d}_{to_d}_lontrn', g['lontrn']), cur_lat, cur_lon)
            lat_err = interp_grid(get_grid_values(f'{from_d}_{to_d}_laterr', g['laterr']), cur_lat, cur_lon)
            lon_err = interp_grid(get_grid_values(f'{from_d}_{to_d}_lonerr', g['lonerr']), cur_lat, cur_lon)
            cur_lat -= lat_shift / 3600.0
            cur_lon -= lon_shift / 3600.0
            sig_lat_sq += lat_err ** 2
            sig_lon_sq += lon_err ** 2

    return cur_lat, cur_lon, math.sqrt(sig_lat_sq), math.sqrt(sig_lon_sq)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def setup_env():
    """Generate grid files and compile Java code."""
    os.makedirs(GRID_DIR, exist_ok=True)

    grid_files = {
        'nadcon5.testregion.datum_a.datum_b.lattrn.b': ab_lattrn,
        'nadcon5.testregion.datum_a.datum_b.laterr.b': ab_laterr,
        'nadcon5.testregion.datum_a.datum_b.lontrn.b': ab_lontrn,
        'nadcon5.testregion.datum_a.datum_b.lonerr.b': ab_lonerr,
        'nadcon5.testregion.datum_b.datum_c.lattrn.b': bc_lattrn,
        'nadcon5.testregion.datum_b.datum_c.laterr.b': bc_laterr,
        'nadcon5.testregion.datum_b.datum_c.lontrn.b': bc_lontrn,
        'nadcon5.testregion.datum_b.datum_c.lonerr.b': bc_lonerr,
    }

    for fname, func in grid_files.items():
        values = generate_grid_values(func)
        write_binary_grid(os.path.join(GRID_DIR, fname), values)

    result = subprocess.run(
        ['bash', '/app/compile.sh'],
        capture_output=True, text=True, cwd='/app'
    )
    if result.returncode != 0:
        pytest.fail(f"Java compilation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")


def run_java_transform(lat, lon_west, src, dest):
    """Run the Java TransformEngine and parse output."""
    cmd = [
        'java', '-cp', '/app/build',
        'gov.noaa.ngs.transform.TransformEngine',
        str(lat), str(lon_west), src, dest
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        pytest.fail(
            f"Java transform failed for ({lat}, {lon_west}, {src}->{dest}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    parts = result.stdout.strip().split(',')
    if len(parts) != 4:
        pytest.fail(f"Unexpected output format: {result.stdout.strip()}")
    return tuple(float(p) for p in parts)

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

TEST_CASES = [
    # (lat, lon_west, src, dest, description)
    # Single-step forward/backward
    (40.0, -80.0, 'DATUM_A', 'DATUM_B', 'forward_ab_gridpoint'),
    (40.15, -80.53, 'DATUM_A', 'DATUM_B', 'forward_ab_interp'),
    (40.0, -80.0, 'DATUM_B', 'DATUM_A', 'backward_ba_gridpoint'),
    (39.88, -80.27, 'DATUM_C', 'DATUM_B', 'backward_cb_interp'),
    # Two-step chains
    (40.0, -80.0, 'DATUM_A', 'DATUM_C', 'forward_ac_chain_gridpoint'),
    (39.63, -79.63, 'DATUM_A', 'DATUM_C', 'forward_ac_chain_interp'),
    (40.0, -80.0, 'DATUM_C', 'DATUM_A', 'backward_ca_chain_gridpoint'),
    (40.37, -79.27, 'DATUM_B', 'DATUM_C', 'forward_bc_interp'),
    # Additional coverage
    (39.88, -80.27, 'DATUM_C', 'DATUM_A', 'backward_ca_chain_interp'),
    (39.5, -79.8, 'DATUM_B', 'DATUM_C', 'forward_bc_gridpoint'),
    (40.15, -80.53, 'DATUM_B', 'DATUM_A', 'backward_ba_interp'),
    (39.30, -80.77, 'DATUM_A', 'DATUM_C', 'forward_ac_interior'),
    # Boundary test (detects floor-vs-round bug via out-of-bounds crash)
    (40.88, -80.0, 'DATUM_A', 'DATUM_B', 'forward_ab_near_boundary'),
]


@pytest.mark.parametrize("lat,lon_west,src,dest,desc", TEST_CASES,
                         ids=[t[4] for t in TEST_CASES])
def test_transform(setup_env, lat, lon_west, src, dest, desc):
    """Verify Java transform output matches Python reference within tolerance."""
    # Compute reference in positive-East longitude
    e_lon = lon_west + 360.0 if lon_west < 0 else lon_west
    ref_lat, ref_lon, ref_sig_lat, ref_sig_lon = transform_ref(lat, e_lon, src, dest)
    ref_lon_west = ref_lon - 360.0 if ref_lon > 180 else ref_lon

    # Run Java
    j_lat, j_lon, j_sig_lat, j_sig_lon = run_java_transform(lat, lon_west, src, dest)

    # Compare coordinates (tolerance ~0.001 mm)
    assert abs(j_lat - ref_lat) < 1e-8, \
        f"[{desc}] lat: java={j_lat:.12f} ref={ref_lat:.12f} diff={abs(j_lat - ref_lat):.2e}"
    assert abs(j_lon - ref_lon_west) < 1e-8, \
        f"[{desc}] lon: java={j_lon:.12f} ref={ref_lon_west:.12f} diff={abs(j_lon - ref_lon_west):.2e}"

    # Compare error estimates (tolerance ~0.01 milli-arcsecond)
    assert abs(j_sig_lat - ref_sig_lat) < 1e-5, \
        f"[{desc}] sigLat: java={j_sig_lat:.8f} ref={ref_sig_lat:.8f}"
    assert abs(j_sig_lon - ref_sig_lon) < 1e-5, \
        f"[{desc}] sigLon: java={j_sig_lon:.8f} ref={ref_sig_lon:.8f}"


def test_compilation_produces_classes(setup_env):
    """Verify that all expected class files exist after compilation."""
    class_dir = "/app/build/gov/noaa/ngs/transform"
    expected = [
        "GridFile.class",
        "GridParser.class",
        "BlockExtractor.class",
        "BiquadraticInterpolator.class",
        "DatumChainTransformer.class",
        "TransformResult.class",
        "TransformEngine.class",
        "RegionConfig.class",
    ]
    for cls in expected:
        path = os.path.join(class_dir, cls)
        assert os.path.exists(path), f"Missing compiled class: {path}"


def test_grid_files_exist(setup_env):
    """Verify that all expected grid files were generated."""
    expected_grids = [
        'nadcon5.testregion.datum_a.datum_b.lattrn.b',
        'nadcon5.testregion.datum_a.datum_b.laterr.b',
        'nadcon5.testregion.datum_a.datum_b.lontrn.b',
        'nadcon5.testregion.datum_a.datum_b.lonerr.b',
        'nadcon5.testregion.datum_b.datum_c.lattrn.b',
        'nadcon5.testregion.datum_b.datum_c.laterr.b',
        'nadcon5.testregion.datum_b.datum_c.lontrn.b',
        'nadcon5.testregion.datum_b.datum_c.lonerr.b',
    ]
    for gf in expected_grids:
        path = os.path.join(GRID_DIR, gf)
        assert os.path.exists(path), f"Missing grid file: {path}"
        size = os.path.getsize(path)
        expected_size = 40 + NROWS * NCOLS * 4  # header + data
        assert size == expected_size, \
            f"Grid file {gf} has size {size}, expected {expected_size}"
