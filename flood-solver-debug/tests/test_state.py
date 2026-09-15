"""
Tests for the 2D shallow water flood inundation solver.
Validates physical correctness of solver output against
invariants of the local inertial formulation on a symmetric valley.
"""


import os
import math

# ----- helpers -----

def read_asc(path):
    """Read an ESRI ASCII raster file. Returns (header_dict, 2D list of floats)."""
    with open(path) as f:
        header = {}
        for _ in range(6):
            parts = f.readline().split()
            header[parts[0].lower()] = float(parts[1])
        nrows = int(header["nrows"])
        ncols = int(header["ncols"])
        data = []
        for _ in range(nrows):
            row = [float(x) for x in f.readline().split()]
            assert len(row) == ncols
            data.append(row)
    return header, data


def read_mass(path):
    """Read the mass balance summary file."""
    vals = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                vals[parts[0]] = float(parts[1])
    return vals


def read_gauges(path):
    """Read gauge CSV. Returns (column_names, list-of-row-dicts)."""
    with open(path) as f:
        header = f.readline().strip().split(",")
        rows = []
        for line in f:
            vals = line.strip().split(",")
            row = {header[k]: float(vals[k]) for k in range(len(header))}
            rows.append(row)
    return header, rows


# DEM floor elevation at a given row (for gauge WSE computation)
def dem_floor(row_idx):
    return 10.0 - row_idx * 0.04


# ----- tests -----

def test_output_files_exist():
    """Solver must produce all expected output files."""
    assert os.path.isfile("/app/results_final.asc"), "Missing results_final.asc"
    assert os.path.isfile("/app/results_gauges.csv"), "Missing results_gauges.csv"
    assert os.path.isfile("/app/results_mass.txt"), "Missing results_mass.txt"


def test_no_negative_depths():
    """All water depths in the final map must be >= 0."""
    _, data = read_asc("/app/results_final.asc")
    for j, row in enumerate(data):
        for i, val in enumerate(row):
            assert val >= 0.0, f"Negative depth {val} at row={j} col={i}"


def test_water_present():
    """Water must be present in the valley (max depth > 0.1 m)."""
    _, data = read_asc("/app/results_final.asc")
    max_depth = max(val for row in data for val in row)
    assert max_depth > 0.1, f"Max water depth {max_depth} m is too low"


def test_reasonable_depth():
    """Maximum water depth must be < 5.0 m (physically bounded)."""
    _, data = read_asc("/app/results_final.asc")
    max_depth = max(val for row in data for val in row)
    assert max_depth < 5.0, f"Max water depth {max_depth} m is unreasonably large"


def test_mass_conservation():
    """Mass conservation error must be < 2% of total inflow."""
    mass = read_mass("/app/results_mass.txt")
    err_pct = mass["mass_error_pct"]
    assert err_pct < 2.0, f"Mass error {err_pct:.2f}% exceeds 2% threshold"


def test_outflow_exists():
    """Water must exit through the south boundary."""
    mass = read_mass("/app/results_mass.txt")
    assert mass["total_outflow_m3"] > 0, "No outflow recorded at south boundary"


def test_downstream_wse():
    """Water surface elevation must decrease from upstream to downstream gauges.

    Gauge rows: upstream=3, middle=7, downstream=12.
    WSE = DEM_floor + water_depth.
    """
    _, gauge_rows = read_gauges("/app/results_gauges.csv")
    assert len(gauge_rows) > 0, "No gauge data"

    # Use the last recorded time step (closest to steady state)
    last = gauge_rows[-1]
    wse_up   = dem_floor(3)  + last["upstream"]
    wse_mid  = dem_floor(7)  + last["middle"]
    wse_down = dem_floor(12) + last["downstream"]

    assert wse_up > wse_down, (
        f"WSE does not decrease downstream: up={wse_up:.4f}, down={wse_down:.4f}"
    )
    assert wse_up >= wse_mid >= wse_down - 0.01, (
        f"WSE ordering violated: up={wse_up:.4f}, mid={wse_mid:.4f}, down={wse_down:.4f}"
    )


def test_symmetry():
    """Final depth profile must be approximately symmetric about the valley centreline.

    DEM has 21 columns, symmetric about column 10.
    Mirrored-column RMSE must be < 0.02 m.
    """
    header, data = read_asc("/app/results_final.asc")
    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    assert ncols == 21

    sum_sq = 0.0
    count = 0
    for j in range(nrows):
        for i in range(ncols // 2):
            mirror = ncols - 1 - i
            diff = data[j][i] - data[j][mirror]
            sum_sq += diff * diff
            count += 1

    rmse = math.sqrt(sum_sq / count)
    assert rmse < 0.02, f"Symmetry RMSE {rmse:.4f} m exceeds 0.02 m threshold"


def test_gauge_steady_state():
    """Downstream gauge depth must converge to near-steady state.

    The last 5 gauge readings should show stable depth values,
    indicating the simulation ran long enough and the solver is
    numerically well-behaved (no oscillations or drift).
    """
    _, gauge_rows = read_gauges("/app/results_gauges.csv")
    assert len(gauge_rows) >= 5, "Not enough gauge data for convergence check"

    # Check last 5 readings at downstream gauge
    last_5 = [r["downstream"] for r in gauge_rows[-5:]]
    mean_val = sum(last_5) / len(last_5)

    if mean_val > 0.01:  # Only check if there is meaningful depth
        max_dev = max(abs(v - mean_val) for v in last_5)
        rel_dev = max_dev / mean_val
        assert rel_dev < 0.15, (
            f"Downstream gauge not converging: max relative deviation "
            f"{rel_dev:.3f} (values: {[f'{v:.4f}' for v in last_5]})"
        )


def test_inflow_outflow_balance():
    """At end of simulation, outflow should approach inflow.

    For a 1800 s simulation with 15 m3/s steady inflow and free-outflow
    south boundary, total outflow should exceed 50% of total inflow once
    the flow has traversed the domain and reached near-steady state.
    """
    mass = read_mass("/app/results_mass.txt")
    inflow = mass["total_inflow_m3"]
    outflow = mass["total_outflow_m3"]
    assert inflow > 0, "No inflow recorded"
    ratio = outflow / inflow
    assert ratio > 0.5, (
        f"Outflow/inflow ratio {ratio:.3f} too low — water not reaching south boundary"
    )


def test_flow_arrival_order():
    """Water must arrive at the upstream gauge before the downstream gauge.

    The point source is near the north boundary, so flow propagates
    southward. The upstream gauge (row 3) should register water depth
    before the downstream gauge (row 12).
    """
    _, gauge_rows = read_gauges("/app/results_gauges.csv")
    assert len(gauge_rows) >= 2, "Not enough gauge data"

    upstream_arrival = None
    downstream_arrival = None

    for row in gauge_rows:
        if upstream_arrival is None and row["upstream"] > 0.001:
            upstream_arrival = row["time"]
        if downstream_arrival is None and row["downstream"] > 0.001:
            downstream_arrival = row["time"]

    assert upstream_arrival is not None, "Water never reached upstream gauge"
    assert downstream_arrival is not None, "Water never reached downstream gauge"
    assert upstream_arrival < downstream_arrival, (
        f"Water reached downstream ({downstream_arrival:.1f}s) "
        f"before upstream ({upstream_arrival:.1f}s) — flow direction may be wrong"
    )


def test_step_count():
    """Simulation must complete in a physically reasonable number of timesteps.

    With CFL-adaptive timestepping on a 21x15 grid at 20 m resolution
    and 1800 s simulation time, the step count should reflect stable
    explicit integration with reasonable Courant numbers.
    """
    mass = read_mass("/app/results_mass.txt")
    steps = int(mass["steps"])
    assert 100 < steps < 100000, (
        f"Step count {steps} outside reasonable range (100, 100000) — "
        f"check CFL timestep computation"
    )
