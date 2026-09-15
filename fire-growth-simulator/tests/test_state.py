
"""Tests for the wildland fire behavior and growth simulator with GDAL/SQLite I/O."""

import csv
import io
import json
import math
import os
import sqlite3
import subprocess
import tempfile

import numpy as np
import pytest
from osgeo import gdal, osr

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NODATA = -9999.0
XLL = 500000.0
YLL_TOP = 4000000.0

PRJ_WKT = (
    'PROJCS["WGS_1984_UTM_Zone_10N",'
    'GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],'
    'PARAMETER["False_Easting",500000.0],'
    'PARAMETER["False_Northing",0.0],'
    'PARAMETER["Central_Meridian",-123.0],'
    'PARAMETER["Scale_Factor",0.9996],'
    'PARAMETER["Latitude_Of_Origin",0.0],'
    'UNIT["Meter",1.0]]'
)

DEFAULT_MOISTURE = {
    "m_1h": 0.06, "m_10h": 0.07, "m_100h": 0.08,
    "m_live_herb": 0.60, "m_live_woody": 0.90,
}

RASTER_NAMES = [
    "rate_of_spread", "fireline_intensity", "flame_length",
    "heading_direction", "eccentricity", "arrival_time",
]

GOLDEN_ROS = {
    1: 103.28, 2: 40.22, 3: 129.56, 4: 89.72, 5: 29.05,
    6: 37.23, 7: 32.76, 8: 2.23, 9: 9.65, 10: 10.03,
    11: 6.73, 12: 14.63, 13: 17.66,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def uniform_grid(val, rows, cols):
    return [[val] * cols for _ in range(rows)]


def write_asc(path, grid, cellsize=100.0):
    rows = len(grid)
    cols = len(grid[0])
    yll = YLL_TOP - rows * cellsize
    with open(path, "w") as f:
        f.write(f"ncols {cols}\n")
        f.write(f"nrows {rows}\n")
        f.write(f"xllcorner {XLL}\n")
        f.write(f"yllcorner {yll}\n")
        f.write(f"cellsize {cellsize}\n")
        f.write("NODATA_value -9999\n")
        for row in grid:
            f.write(" ".join(str(v) for v in row) + "\n")


def write_prj(path):
    with open(path, "w") as f:
        f.write(PRJ_WKT)


def create_fuel_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fuel_models (
            fm_num INTEGER PRIMARY KEY, fm_code TEXT, is_dynamic INTEGER,
            depth_ft REAL, mx_dead_pct REAL, load_1h_tpa REAL,
            load_10h_tpa REAL, load_100h_tpa REAL, load_herb_tpa REAL,
            load_woody_tpa REAL, sav_1h REAL, sav_herb REAL, sav_woody REAL)"""
    )
    with open("/app/fuel_models.csv") as f:
        lines = [l for l in f if not l.startswith("#")]
    for row in csv.DictReader(io.StringIO("".join(lines))):
        conn.execute(
            "INSERT OR REPLACE INTO fuel_models VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(row["fm_num"]), row["fm_code"], int(row["is_dynamic"]),
                float(row["depth_ft"]), float(row["mx_dead_pct"]),
                float(row["load_1h_tpa"]), float(row["load_10h_tpa"]),
                float(row["load_100h_tpa"]), float(row["load_herb_tpa"]),
                float(row["load_woody_tpa"]), float(row["sav_1h"]),
                float(row["sav_herb"]), float(row["sav_woody"]),
            ),
        )
    conn.commit()
    conn.close()


def run_sim(
    fuel_grid,
    slope_grid=None,
    aspect_grid=None,
    moisture=None,
    wind_mph=5.0,
    wind_dir=0.0,
    ignitions=None,
    max_time=120.0,
    cellsize=100.0,
    db_modifier=None,
):
    """Create GDAL inputs, populate SQLite DB, run simulator, read GeoTIFF outputs."""
    rows = len(fuel_grid)
    cols = len(fuel_grid[0])
    if slope_grid is None:
        slope_grid = uniform_grid(0.0, rows, cols)
    if aspect_grid is None:
        aspect_grid = uniform_grid(0.0, rows, cols)
    if moisture is None:
        moisture = dict(DEFAULT_MOISTURE)
    if ignitions is None:
        ignitions = [[rows // 2, cols // 2]]

    tmpdir = tempfile.mkdtemp()
    land_dir = os.path.join(tmpdir, "landscape")
    out_dir = os.path.join(tmpdir, "output")
    os.makedirs(land_dir)
    os.makedirs(out_dir)

    write_asc(os.path.join(land_dir, "fuel_model.asc"), fuel_grid, cellsize)
    write_asc(os.path.join(land_dir, "slope.asc"), slope_grid, cellsize)
    write_asc(os.path.join(land_dir, "aspect.asc"), aspect_grid, cellsize)
    for name in ("fuel_model", "slope", "aspect"):
        write_prj(os.path.join(land_dir, f"{name}.prj"))

    db_path = os.path.join(tmpdir, "fuel_params.db")
    create_fuel_db(db_path)

    if db_modifier is not None:
        db_modifier(db_path)

    cfg = {
        "landscape_dir": land_dir,
        "fuel_db": db_path,
        "output_dir": out_dir,
        "moisture": moisture,
        "wind": {"speed_mph": wind_mph, "direction_from_deg": wind_dir},
        "ignitions": ignitions,
        "max_time_min": max_time,
    }
    cfg_path = os.path.join(tmpdir, "config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)

    r = subprocess.run(
        ["python3", "/app/firesim.py", cfg_path],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, (
        f"firesim.py failed (rc={r.returncode}):\n{r.stderr}\n{r.stdout}"
    )

    result = {"out_dir": out_dir, "land_dir": land_dir, "cellsize": cellsize}
    for name in RASTER_NAMES:
        tif_path = os.path.join(out_dir, f"{name}.tif")
        assert os.path.exists(tif_path), f"Missing output: {name}.tif"
        ds = gdal.Open(tif_path)
        assert ds is not None, f"Cannot open {name}.tif with GDAL"
        band = ds.GetRasterBand(1)
        result[name] = band.ReadAsArray()
        result[f"{name}_nodata"] = band.GetNoDataValue()
        if name == RASTER_NAMES[0]:
            result["gt"] = ds.GetGeoTransform()
            result["proj"] = ds.GetProjection()
            result["xsize"] = ds.RasterXSize
            result["ysize"] = ds.RasterYSize
        ds = None

    summary_path = os.path.join(out_dir, "summary.json")
    assert os.path.exists(summary_path), "Missing summary.json"
    with open(summary_path) as f:
        result["summary"] = json.load(f)

    return result


def is_nodata(val):
    return abs(float(val) - NODATA) < 0.5


# ===================================================================
# 1. GeoTIFF I/O and metadata tests
# ===================================================================
def test_output_geotiff_exists():
    """All output GeoTIFF files and summary.json must be created."""
    result = run_sim(uniform_grid(1, 3, 3))
    for name in RASTER_NAMES:
        assert os.path.exists(os.path.join(result["out_dir"], f"{name}.tif"))
    assert os.path.exists(os.path.join(result["out_dir"], "summary.json"))


def test_output_geotiff_dimensions():
    """Output GeoTIFF dimensions must match input raster."""
    result = run_sim(uniform_grid(1, 5, 7))
    assert result["ysize"] == 5, f"Expected 5 rows, got {result['ysize']}"
    assert result["xsize"] == 7, f"Expected 7 cols, got {result['xsize']}"


def test_output_geotiff_geotransform():
    """Output GeoTIFF must preserve geotransform from input .asc rasters."""
    cellsize = 100.0
    rows, cols = 5, 5
    result = run_sim(uniform_grid(1, rows, cols), cellsize=cellsize)
    gt = result["gt"]
    expected = (XLL, cellsize, 0.0, YLL_TOP, 0.0, -cellsize)
    for i in range(6):
        assert abs(gt[i] - expected[i]) < 0.01, (
            f"Geotransform[{i}]: {gt[i]} != {expected[i]}"
        )


def test_output_geotiff_nodata_value():
    """All output GeoTIFFs must declare -9999 as nodata."""
    result = run_sim(uniform_grid(1, 3, 3))
    for name in RASTER_NAMES:
        nd = result[f"{name}_nodata"]
        assert nd is not None and abs(nd - NODATA) < 0.5, (
            f"{name}.tif nodata should be -9999, got {nd}"
        )


def test_output_geotiff_crs_preservation():
    """Output GeoTIFF must preserve CRS from input .prj sidecar."""
    result = run_sim(uniform_grid(1, 3, 3))
    proj = result["proj"]
    assert proj and len(proj) > 0, "Output GeoTIFF must have CRS"
    assert "PROJCS" in proj, "Output CRS must be projected"
    out_srs = osr.SpatialReference()
    out_srs.ImportFromWkt(proj)
    in_srs = osr.SpatialReference()
    in_srs.ImportFromWkt(PRJ_WKT)
    assert out_srs.IsSame(in_srs), "Output CRS must match input CRS"


# ===================================================================
# 2. Golden-master ROS for all 13 standard fuel models
# ===================================================================
@pytest.mark.parametrize("fm,expected", sorted(GOLDEN_ROS.items()))
def test_golden_master_ros(fm, expected):
    result = run_sim(uniform_grid(fm, 3, 3))
    ros = float(result["rate_of_spread"][1, 1])
    assert abs(ros - expected) < 0.15, (
        f"FM{fm}: ROS={ros:.4f}, expected={expected:.2f}"
    )


# ===================================================================
# 3. Physical property tests
# ===================================================================
def test_wind_increases_ros():
    calm = run_sim(uniform_grid(1, 3, 3), wind_mph=0.0)
    windy = run_sim(uniform_grid(1, 3, 3), wind_mph=10.0)
    assert float(windy["rate_of_spread"][1, 1]) > float(calm["rate_of_spread"][1, 1])


def test_slope_increases_ros():
    flat = run_sim(uniform_grid(1, 3, 3), wind_mph=0.0)
    sloped = run_sim(
        uniform_grid(1, 3, 3), wind_mph=0.0,
        slope_grid=uniform_grid(30.0, 3, 3),
        aspect_grid=uniform_grid(180.0, 3, 3),
    )
    assert float(sloped["rate_of_spread"][1, 1]) > float(flat["rate_of_spread"][1, 1])


def test_moisture_decreases_ros():
    dry = run_sim(uniform_grid(1, 3, 3))
    wet_m = dict(DEFAULT_MOISTURE)
    wet_m["m_1h"] = 0.10
    wet_m["m_10h"] = 0.11
    wet_m["m_100h"] = 0.12
    wet = run_sim(uniform_grid(1, 3, 3), moisture=wet_m)
    assert float(dry["rate_of_spread"][1, 1]) > float(wet["rate_of_spread"][1, 1])


def test_zero_ros_at_extinction():
    """FM8 has mx_dead=30%. At 30% dead moisture, ROS must be ~0."""
    ext_m = dict(DEFAULT_MOISTURE)
    ext_m["m_1h"] = 0.30
    ext_m["m_10h"] = 0.30
    ext_m["m_100h"] = 0.30
    result = run_sim(uniform_grid(8, 3, 3), wind_mph=0.0, moisture=ext_m)
    ros = float(result["rate_of_spread"][1, 1])
    assert ros < 0.01 or is_nodata(ros)


def test_nonneg_outputs():
    for fm in [1, 4, 8, 13]:
        result = run_sim(uniform_grid(fm, 3, 3))
        for key in ("rate_of_spread", "fireline_intensity", "flame_length"):
            arr = result[key]
            for r in range(3):
                for c in range(3):
                    val = float(arr[r, c])
                    assert val >= 0.0 or is_nodata(val), (
                        f"FM{fm} {key} has invalid value {val}"
                    )


# ===================================================================
# 4. Flame-length consistency
# ===================================================================
def test_flame_length_formula():
    """flame_length must equal 0.45 * fireline_intensity^0.46."""
    result = run_sim(uniform_grid(4, 3, 3))
    for r in range(3):
        for c in range(3):
            fli = float(result["fireline_intensity"][r, c])
            fl = float(result["flame_length"][r, c])
            if not is_nodata(fli) and fli > 0:
                expected = 0.45 * fli ** 0.46
                assert abs(fl - expected) < 0.05, (
                    f"FL mismatch at ({r},{c}): {fl:.4f} vs {expected:.4f}"
                )


def test_flame_length_monotonic_in_wind():
    low = run_sim(uniform_grid(4, 3, 3), wind_mph=5.0)
    high = run_sim(uniform_grid(4, 3, 3), wind_mph=10.0)
    assert float(high["fireline_intensity"][1, 1]) > float(low["fireline_intensity"][1, 1])
    assert float(high["flame_length"][1, 1]) > float(low["flame_length"][1, 1])


# ===================================================================
# 5. Heading direction and eccentricity
# ===================================================================
def test_heading_with_north_wind():
    """Wind from north pushes fire south => heading ~ 180 deg."""
    result = run_sim(uniform_grid(1, 5, 5), wind_mph=5.0, wind_dir=0.0)
    h = float(result["heading_direction"][2, 2])
    assert 170 < h < 190, f"Heading should be ~180, got {h}"


def test_heading_with_east_wind():
    """Wind from east pushes fire west => heading ~ 270 deg."""
    result = run_sim(uniform_grid(1, 5, 5), wind_mph=5.0, wind_dir=90.0)
    h = float(result["heading_direction"][2, 2])
    assert 260 < h < 280, f"Heading should be ~270, got {h}"


def test_eccentricity_with_wind():
    result = run_sim(uniform_grid(1, 5, 5), wind_mph=5.0)
    e = float(result["eccentricity"][2, 2])
    assert 0.0 < e < 1.0, f"Eccentricity should be in (0,1), got {e}"


def test_eccentricity_no_wind_flat():
    result = run_sim(uniform_grid(1, 5, 5), wind_mph=0.0)
    e = float(result["eccentricity"][2, 2])
    assert abs(e) < 0.01 or is_nodata(e), f"No-wind eccentricity should be ~0, got {e}"


# ===================================================================
# 6. Fire growth arrival-time tests
# ===================================================================
def test_arrival_at_ignition():
    result = run_sim(uniform_grid(1, 5, 5))
    t = float(result["arrival_time"][2, 2])
    assert t == 0.0, f"Ignition cell should have arrival_time=0, got {t}"


def test_arrival_increases_with_distance():
    result = run_sim(
        uniform_grid(1, 9, 9), wind_mph=0.0, cellsize=50.0,
    )
    center = 4
    t0 = float(result["arrival_time"][center, center])
    t1 = float(result["arrival_time"][center, center + 1])
    t2 = float(result["arrival_time"][center, center + 2])
    assert t0 == 0.0
    assert not is_nodata(t1) and t1 > 0
    assert not is_nodata(t2) and t2 > t1


def test_wind_asymmetric_arrival():
    """With wind from north, fire reaches cells to the south faster."""
    result = run_sim(
        uniform_grid(1, 11, 11), wind_mph=5.0, wind_dir=0.0, cellsize=50.0,
    )
    cr, cc = 5, 5
    t_south = float(result["arrival_time"][cr + 2, cc])
    t_north = float(result["arrival_time"][cr - 2, cc])
    assert not is_nodata(t_south) and not is_nodata(t_north)
    assert t_south < t_north, (
        f"Downwind {t_south:.4f} should be < upwind {t_north:.4f}"
    )


def test_no_wind_circular_symmetry():
    """Without wind on flat terrain, cardinal neighbours have equal arrival times."""
    result = run_sim(
        uniform_grid(1, 7, 7), wind_mph=0.0, cellsize=50.0,
    )
    c = 3
    times = []
    for dr, dc in [(-1, 0), (1, 0), (0, 1), (0, -1)]:
        t = float(result["arrival_time"][c + dr, c + dc])
        assert not is_nodata(t), "Cardinal neighbours must be reached"
        times.append(t)
    avg = sum(times) / len(times)
    for t in times:
        assert abs(t - avg) / avg < 0.05, f"Symmetry broken: times={times}"


# ===================================================================
# 7. Nonburnable barrier
# ===================================================================
def test_nonburnable_blocks_fire():
    """A thick NB barrier blocks fire propagation."""
    rows, cols = 11, 11
    fuel = [[1] * cols for _ in range(rows)]
    for r in range(4, 7):
        for c_ in range(cols):
            fuel[r][c_] = 91
    result = run_sim(
        fuel, wind_mph=5.0, wind_dir=0.0, ignitions=[[2, 5]], max_time=120.0,
    )
    for r in range(4, 7):
        for c_ in range(cols):
            assert is_nodata(result["arrival_time"][r, c_]), (
                f"NB cell ({r},{c_}) should have nodata arrival"
            )
    for r in range(7, rows):
        for c_ in range(cols):
            assert is_nodata(result["arrival_time"][r, c_]), (
                f"Cell ({r},{c_}) past barrier should be unreached"
            )


def test_nonburnable_nodata_outputs():
    """NB fuel model cells should have nodata in all output bands."""
    result = run_sim(uniform_grid(91, 3, 3))
    for key in RASTER_NAMES:
        arr = result[key]
        for r in range(3):
            for c in range(3):
                assert is_nodata(arr[r, c]), (
                    f"NB model should have nodata in {key}, got {float(arr[r, c])}"
                )


# ===================================================================
# 8. Burned area
# ===================================================================
def test_burned_area_calculation():
    result = run_sim(uniform_grid(1, 5, 5), cellsize=100.0)
    cs = 100.0
    arr = result["arrival_time"]
    reached = sum(
        1 for r in range(5) for c in range(5) if not is_nodata(arr[r, c])
    )
    expected = reached * cs * cs
    assert abs(result["summary"]["burned_area_ft2"] - expected) < 1.0


# ===================================================================
# 9. Dynamic fuel model
# ===================================================================
def test_dynamic_model_gr4():
    """GR4 (104) is a dynamic grass model; should produce valid fire behavior."""
    result = run_sim(uniform_grid(104, 3, 3), wind_mph=5.0)
    ros = float(result["rate_of_spread"][1, 1])
    fli = float(result["fireline_intensity"][1, 1])
    fl = float(result["flame_length"][1, 1])
    assert ros > 0.0 and not is_nodata(ros), "GR4 should produce positive ROS"
    assert fli > 0.0
    assert fl > 0.0


def test_dynamic_curing_affects_ros():
    """Different live herb moisture produces different ROS in dynamic model."""
    m_dry = dict(DEFAULT_MOISTURE)
    m_dry["m_live_herb"] = 0.30
    m_wet = dict(DEFAULT_MOISTURE)
    m_wet["m_live_herb"] = 1.20
    dry = run_sim(uniform_grid(104, 3, 3), wind_mph=5.0, moisture=m_dry)
    wet = run_sim(uniform_grid(104, 3, 3), wind_mph=5.0, moisture=m_wet)
    r_dry = float(dry["rate_of_spread"][1, 1])
    r_wet = float(wet["rate_of_spread"][1, 1])
    assert abs(r_dry - r_wet) > 0.5, (
        f"Dynamic curing should produce different ROS: dry={r_dry}, wet={r_wet}"
    )


# ===================================================================
# 10. Multiple ignitions
# ===================================================================
def test_multiple_ignitions():
    result = run_sim(
        uniform_grid(1, 9, 9), wind_mph=0.0, cellsize=50.0,
        ignitions=[[2, 4], [6, 4]],
    )
    assert float(result["arrival_time"][2, 4]) == 0.0
    assert float(result["arrival_time"][6, 4]) == 0.0
    t_mid = float(result["arrival_time"][4, 4])
    assert not is_nodata(t_mid) and t_mid > 0


# ===================================================================
# 11. Slope + wind vector combination
# ===================================================================
def test_slope_wind_interaction():
    """When slope and wind interact, heading ROS differs from wind-only case."""
    wind_only = run_sim(uniform_grid(1, 3, 3), wind_mph=5.0, wind_dir=0.0)
    combined = run_sim(
        uniform_grid(1, 3, 3), wind_mph=5.0, wind_dir=0.0,
        slope_grid=uniform_grid(30.0, 3, 3),
        aspect_grid=uniform_grid(180.0, 3, 3),
    )
    r_wind = float(wind_only["rate_of_spread"][1, 1])
    r_comb = float(combined["rate_of_spread"][1, 1])
    assert abs(r_wind - r_comb) > 1.0


# ===================================================================
# 12. SQLite parameter verification
# ===================================================================
def test_sqlite_fuel_params_used():
    """Verify simulator queries fuel params from SQLite (not hardcoded).
    Modify FM1 depth in the DB and confirm ROS changes from golden master."""
    def modify_depth(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE fuel_models SET depth_ft = 0.5 WHERE fm_num = 1")
        conn.commit()
        conn.close()

    result = run_sim(
        uniform_grid(1, 3, 3), wind_mph=5.0, wind_dir=0.0,
        db_modifier=modify_depth,
    )
    ros = float(result["rate_of_spread"][1, 1])
    assert abs(ros - 103.28) > 1.0, (
        f"With modified fuel DB (depth=0.5), ROS should differ from "
        f"golden master 103.28. Got {ros}"
    )


# ===================================================================
# 13. Unrecognized fuel model
# ===================================================================
def test_unrecognized_fuel_model():
    """Unrecognized fuel model numbers must be treated as non-burnable."""
    result = run_sim(uniform_grid(999, 3, 3))
    for key in RASTER_NAMES:
        arr = result[key]
        for r in range(3):
            for c in range(3):
                assert is_nodata(arr[r, c]), (
                    f"Unrecognized FM999 should have nodata in {key}, "
                    f"got {float(arr[r, c])}"
                )
