
import pytest
import csv
import os
import subprocess
import math
import json

from osgeo import gdal, osr
import numpy as np


def run_simulation():
    """Run the simulation and return (success, stdout, stderr)."""
    result = subprocess.run(
        ["python3", "/app/run_simulation.py"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd="/app",
    )
    return result.returncode == 0, result.stdout, result.stderr


def parse_totals(path="/app/output/totals.csv"):
    totals = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            totals[row["variable"]] = float(row["value"])
    return totals


def parse_series(path):
    records = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({k: float(v) for k, v in row.items()})
    return records


def read_asc(path):
    """Read ESRI ASCII Grid file. Returns (header_dict, 2D_data_list)."""
    header = {}
    with open(path) as f:
        for _ in range(6):
            parts = f.readline().strip().split(None, 1)
            key = parts[0].lower()
            val = parts[1]
            if key in ("ncols", "nrows"):
                header[key] = int(val)
            elif key == "nodata_value":
                header["nodata_value"] = float(val)
            else:
                header[key] = float(val)
        data = []
        for _ in range(header["nrows"]):
            row = list(map(float, f.readline().strip().split()))
            data.append(row)
    return header, data


def read_params_csv(path):
    """Read parameter lookup table CSV."""
    params = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = int(row["type"])
            params[tid] = {k: float(v) for k, v in row.items() if k != "type"}
    return params


def read_geotiff(path):
    """Read a GeoTIFF file via GDAL. Returns dict with metadata and data array."""
    ds = gdal.Open(path)
    if ds is None:
        return None
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    nodata = band.GetNoDataValue()
    xsize = ds.RasterXSize
    ysize = ds.RasterYSize
    dtype = band.DataType
    ds = None
    return {
        "data": data,
        "gt": gt,
        "projection": proj,
        "nodata": nodata,
        "xsize": xsize,
        "ysize": ysize,
        "dtype": dtype,
    }


@pytest.fixture(scope="session")
def simulation_output():
    """Run the simulation once and return parsed outputs."""
    success, stdout, stderr = run_simulation()
    assert success, f"Simulation failed.\nstdout: {stdout[-2000:]}\nstderr: {stderr[-2000:]}"
    totals = parse_totals()
    series = parse_series("/app/output/totalseries.csv")
    hydro = parse_series("/app/output/hydrograph.csv")
    return totals, series, hydro


@pytest.fixture(scope="session")
def dem_data():
    return read_asc("/app/dem.asc")


@pytest.fixture(scope="session")
def lc_params():
    return read_params_csv("/app/landcover_params.csv")


# ---------------------------------------------------------------------------
# Output file existence and CSV format
# ---------------------------------------------------------------------------
class TestOutputFiles:
    def test_totals_exists(self, simulation_output):
        assert os.path.exists("/app/output/totals.csv")

    def test_totalseries_exists(self, simulation_output):
        assert os.path.exists("/app/output/totalseries.csv")

    def test_hydrograph_exists(self, simulation_output):
        assert os.path.exists("/app/output/hydrograph.csv")

    def test_flowdir_tif_exists(self, simulation_output):
        assert os.path.exists("/app/output/flowdir.tif")

    def test_flowacc_tif_exists(self, simulation_output):
        assert os.path.exists("/app/output/flowacc.tif")

    def test_maxdepth_tif_exists(self, simulation_output):
        assert os.path.exists("/app/output/maxdepth.tif")

    def test_flood_extent_exists(self, simulation_output):
        assert os.path.exists("/app/output/flood_extent.geojson")

    def test_totals_has_required_variables(self, simulation_output):
        totals, _, _ = simulation_output
        required = [
            "total_rainfall_mm",
            "total_interception_mm",
            "total_infiltration_mm",
            "total_outflow_mm",
            "peak_discharge_m3s",
            "peak_time_min",
            "mass_balance_error_pct",
            "runoff_coefficient",
        ]
        for key in required:
            assert key in totals, f"Missing variable '{key}' in totals.csv"

    def test_totalseries_has_required_columns(self, simulation_output):
        _, series, _ = simulation_output
        assert len(series) > 0, "totalseries.csv is empty"
        required = [
            "time_min",
            "rainfall_mm",
            "interception_mm",
            "infiltration_mm",
            "surface_storage_mm",
            "outflow_mm",
            "mass_balance_error_pct",
        ]
        for key in required:
            assert key in series[0], f"Missing column '{key}' in totalseries.csv"

    def test_hydrograph_has_required_columns(self, simulation_output):
        _, _, hydro = simulation_output
        assert len(hydro) > 0, "hydrograph.csv is empty"
        for key in ["time_min", "discharge_m3s"]:
            assert key in hydro[0], f"Missing column '{key}' in hydrograph.csv"


# ---------------------------------------------------------------------------
# GeoTIFF format validation
# ---------------------------------------------------------------------------
class TestGeoTiffFormat:
    EXPECTED_GT = (500000.0, 20.0, 0.0, 5600300.0, 0.0, -20.0)
    EXPECTED_EPSG = 32632

    def _assert_geotransform(self, info, label):
        for i in range(6):
            assert abs(info["gt"][i] - self.EXPECTED_GT[i]) < 0.01, (
                f"{label} GT[{i}]: {info['gt'][i]} != {self.EXPECTED_GT[i]}"
            )

    def _assert_crs(self, info, label):
        srs = osr.SpatialReference()
        srs.ImportFromWkt(info["projection"])
        expected_srs = osr.SpatialReference()
        expected_srs.ImportFromEPSG(self.EXPECTED_EPSG)
        assert srs.IsSame(expected_srs), f"{label} CRS is not EPSG:{self.EXPECTED_EPSG}"

    # flowdir.tif
    def test_flowdir_geotransform(self, simulation_output):
        info = read_geotiff("/app/output/flowdir.tif")
        assert info is not None, "Cannot open flowdir.tif"
        self._assert_geotransform(info, "flowdir.tif")

    def test_flowdir_crs(self, simulation_output):
        info = read_geotiff("/app/output/flowdir.tif")
        self._assert_crs(info, "flowdir.tif")

    def test_flowdir_dimensions(self, simulation_output):
        info = read_geotiff("/app/output/flowdir.tif")
        assert info["xsize"] == 15 and info["ysize"] == 15

    def test_flowdir_nodata(self, simulation_output):
        info = read_geotiff("/app/output/flowdir.tif")
        assert info["nodata"] == -9999

    def test_flowdir_gdalinfo(self, simulation_output):
        result = subprocess.run(
            ["gdalinfo", "/app/output/flowdir.tif"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"gdalinfo failed: {result.stderr[:500]}"

    # maxdepth.tif
    def test_maxdepth_geotransform(self, simulation_output):
        info = read_geotiff("/app/output/maxdepth.tif")
        assert info is not None, "Cannot open maxdepth.tif"
        self._assert_geotransform(info, "maxdepth.tif")

    def test_maxdepth_crs(self, simulation_output):
        info = read_geotiff("/app/output/maxdepth.tif")
        self._assert_crs(info, "maxdepth.tif")

    def test_maxdepth_dimensions(self, simulation_output):
        info = read_geotiff("/app/output/maxdepth.tif")
        assert info["xsize"] == 15 and info["ysize"] == 15

    def test_maxdepth_nodata(self, simulation_output):
        info = read_geotiff("/app/output/maxdepth.tif")
        assert info["nodata"] == -9999

    def test_maxdepth_gdalinfo(self, simulation_output):
        result = subprocess.run(
            ["gdalinfo", "/app/output/maxdepth.tif"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    # flowacc.tif
    def test_flowacc_geotransform(self, simulation_output):
        info = read_geotiff("/app/output/flowacc.tif")
        assert info is not None, "Cannot open flowacc.tif"
        self._assert_geotransform(info, "flowacc.tif")

    def test_flowacc_crs(self, simulation_output):
        info = read_geotiff("/app/output/flowacc.tif")
        self._assert_crs(info, "flowacc.tif")

    def test_flowacc_dimensions(self, simulation_output):
        info = read_geotiff("/app/output/flowacc.tif")
        assert info["xsize"] == 15 and info["ysize"] == 15

    def test_flowacc_nodata(self, simulation_output):
        info = read_geotiff("/app/output/flowacc.tif")
        assert info["nodata"] == -9999

    def test_flowacc_gdalinfo(self, simulation_output):
        result = subprocess.run(
            ["gdalinfo", "/app/output/flowacc.tif"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Flow direction grid (from GeoTIFF)
# ---------------------------------------------------------------------------
class TestFlowDir:
    def test_flowdir_valid_values(self, simulation_output):
        info = read_geotiff("/app/output/flowdir.tif")
        data = info["data"]
        valid_dirs = {1, 2, 3, 4, 5, 6, 7, 8, 9}
        nrows, ncols = data.shape
        for i in range(nrows):
            for j in range(ncols):
                assert int(data[i, j]) in valid_dirs, (
                    f"Invalid flow dir {data[i, j]} at ({i},{j})"
                )

    def test_flowdir_single_outlet(self, simulation_output):
        info = read_geotiff("/app/output/flowdir.tif")
        data = info["data"]
        outlets = list(zip(*np.where(data == 5)))
        assert len(outlets) == 1, f"Expected 1 outlet, found {len(outlets)}: {outlets}"

    def test_outlet_at_lowest_boundary(self, simulation_output, dem_data):
        dem_header, dem = dem_data
        fdir = read_geotiff("/app/output/flowdir.tif")["data"]
        nrows = dem_header["nrows"]
        ncols = dem_header["ncols"]

        outlet = None
        for i in range(nrows):
            for j in range(ncols):
                if int(fdir[i, j]) == 5:
                    outlet = (i, j)

        assert outlet is not None

        min_elev = float("inf")
        min_cell = None
        for i in range(nrows):
            for j in range(ncols):
                if i == 0 or i == nrows - 1 or j == 0 or j == ncols - 1:
                    if dem[i][j] < min_elev:
                        min_elev = dem[i][j]
                        min_cell = (i, j)

        assert outlet == min_cell, (
            f"Outlet at {outlet} (elev={dem[outlet[0]][outlet[1]]:.2f}) "
            f"but lowest boundary cell at {min_cell} (elev={min_elev:.2f})"
        )

    def test_flow_follows_terrain(self, simulation_output, dem_data):
        """Verify that flow directions point downhill."""
        dem_header, dem = dem_data
        fdir = read_geotiff("/app/output/flowdir.tif")["data"]
        nrows = dem_header["nrows"]
        ncols = dem_header["ncols"]

        offsets = {
            7: (-1, -1), 8: (-1, 0), 9: (-1, 1),
            4: (0, -1),              6: (0, 1),
            1: (1, -1),  2: (1, 0),  3: (1, 1),
        }

        violations = 0
        for i in range(nrows):
            for j in range(ncols):
                d = int(fdir[i, j])
                if d == 5:
                    continue
                if d not in offsets:
                    continue
                di, dj = offsets[d]
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    if dem[ni][nj] >= dem[i][j]:
                        violations += 1

        assert violations == 0, f"{violations} cells flow uphill"


# ---------------------------------------------------------------------------
# Flow accumulation
# ---------------------------------------------------------------------------
class TestFlowAccumulation:
    def test_min_accumulation_is_one(self, simulation_output):
        info = read_geotiff("/app/output/flowacc.tif")
        assert info["data"].min() >= 1, (
            f"Min accumulation {info['data'].min()} < 1"
        )

    def test_outlet_has_total_cells(self, simulation_output):
        fdir = read_geotiff("/app/output/flowdir.tif")["data"]
        facc = read_geotiff("/app/output/flowacc.tif")["data"]
        nrows, ncols = fdir.shape
        total_cells = nrows * ncols

        outlet = None
        for i in range(nrows):
            for j in range(ncols):
                if int(fdir[i, j]) == 5:
                    outlet = (i, j)

        assert outlet is not None, "No outlet found in flowdir"
        assert int(facc[outlet[0], outlet[1]]) == total_cells, (
            f"Outlet acc {facc[outlet[0], outlet[1]]} != {total_cells}"
        )

    def test_accumulation_consistent_with_flowdir(self, simulation_output):
        """Each cell's accumulation must equal 1 + sum of acc of upstream neighbors."""
        fdir = read_geotiff("/app/output/flowdir.tif")["data"]
        facc = read_geotiff("/app/output/flowacc.tif")["data"]
        nrows, ncols = fdir.shape

        offsets = {
            7: (-1, -1), 8: (-1, 0), 9: (-1, 1),
            4: (0, -1),              6: (0, 1),
            1: (1, -1),  2: (1, 0),  3: (1, 1),
        }

        errors = 0
        for i in range(nrows):
            for j in range(ncols):
                expected = 1  # self
                for d, (di, dj) in offsets.items():
                    # Cell at (i-di, j-dj) with direction d flows to (i, j)
                    ui, uj = i - di, j - dj
                    if 0 <= ui < nrows and 0 <= uj < ncols:
                        if int(fdir[ui, uj]) == d:
                            expected += int(facc[ui, uj])
                if int(facc[i, j]) != expected:
                    errors += 1

        assert errors == 0, f"{errors} cells have inconsistent flow accumulation"


# ---------------------------------------------------------------------------
# Max depth (GeoTIFF)
# ---------------------------------------------------------------------------
class TestMaxDepth:
    def test_maxdepth_non_negative(self, simulation_output):
        data = read_geotiff("/app/output/maxdepth.tif")["data"]
        assert data.min() >= -1e-6, f"Negative max depth {data.min()}"

    def test_maxdepth_has_positive_values(self, simulation_output):
        data = read_geotiff("/app/output/maxdepth.tif")["data"]
        assert data.max() > 0, "maxdepth grid is all zeros - no ponding occurred"

    def test_maxdepth_physically_plausible(self, simulation_output):
        data = read_geotiff("/app/output/maxdepth.tif")["data"]
        assert data.max() < 1.0, (
            f"Max depth {data.max():.4f} m exceeds 1.0 m - "
            "implausible for this rainfall event"
        )

    def test_maxdepth_highest_in_lower_catchment(self, simulation_output, dem_data):
        """Peak water depth should occur in lower/channel area of catchment."""
        dem_header, _ = dem_data
        data = read_geotiff("/app/output/maxdepth.tif")["data"]
        nrows = dem_header["nrows"]
        max_row = int(np.argmax(data) // data.shape[1])
        assert max_row >= nrows // 3, (
            f"Max depth at row {max_row} - expected in lower 2/3 of catchment"
        )


# ---------------------------------------------------------------------------
# Flood extent GeoJSON
# ---------------------------------------------------------------------------
class TestFloodExtent:
    def test_geojson_valid_structure(self, simulation_output):
        with open("/app/output/flood_extent.geojson") as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection", (
            f"Expected FeatureCollection, got {data.get('type')}"
        )

    def test_geojson_has_features(self, simulation_output):
        with open("/app/output/flood_extent.geojson") as f:
            data = json.load(f)
        assert len(data["features"]) > 0, "No features in flood extent GeoJSON"

    def test_geojson_geometry_type(self, simulation_output):
        with open("/app/output/flood_extent.geojson") as f:
            data = json.load(f)
        for feat in data["features"]:
            gtype = feat["geometry"]["type"]
            assert gtype in ("Polygon", "MultiPolygon"), (
                f"Unexpected geometry type: {gtype}"
            )

    def test_geojson_coordinates_wgs84(self, simulation_output):
        """Coordinates must be in WGS84 range, not raw UTM."""
        with open("/app/output/flood_extent.geojson") as f:
            data = json.load(f)

        def extract_coords(geom):
            if geom["type"] == "Polygon":
                return [c for ring in geom["coordinates"] for c in ring]
            elif geom["type"] == "MultiPolygon":
                return [c for poly in geom["coordinates"]
                        for ring in poly for c in ring]
            return []

        for feat in data["features"]:
            coords = extract_coords(feat["geometry"])
            assert len(coords) > 0, "Feature has no coordinates"
            for coord in coords:
                lon, lat = coord[0], coord[1]
                assert -180 <= lon <= 180, (
                    f"Longitude {lon} outside WGS84 range (UTM not reprojected?)"
                )
                assert -90 <= lat <= 90, (
                    f"Latitude {lat} outside WGS84 range (UTM not reprojected?)"
                )

    def test_geojson_gridcode_property(self, simulation_output):
        with open("/app/output/flood_extent.geojson") as f:
            data = json.load(f)
        for feat in data["features"]:
            assert "gridcode" in feat["properties"], "Missing gridcode property"
            assert feat["properties"]["gridcode"] == 1


# ---------------------------------------------------------------------------
# Total rainfall verification
# ---------------------------------------------------------------------------
class TestTotalRainfall:
    def test_total_rainfall_matches_input(self, simulation_output):
        """Trapezoidal integration of the input hyetograph gives ~33.75 mm."""
        totals, _, _ = simulation_output
        assert abs(totals["total_rainfall_mm"] - 33.75) < 1.0, (
            f"Total rainfall {totals['total_rainfall_mm']:.3f} mm, "
            "expected ~33.75 mm from input hyetograph"
        )


# ---------------------------------------------------------------------------
# Mass balance
# ---------------------------------------------------------------------------
class TestMassBalance:
    def test_final_mass_balance_closure(self, simulation_output):
        totals, _, _ = simulation_output
        assert abs(totals["mass_balance_error_pct"]) < 1.0, (
            f"Final mass balance error {totals['mass_balance_error_pct']:.4f}% "
            "exceeds 1%"
        )

    def test_components_sum_to_rainfall(self, simulation_output):
        totals, series, _ = simulation_output
        rain = totals["total_rainfall_mm"]
        interc = totals["total_interception_mm"]
        infil = totals["total_infiltration_mm"]
        outflow = totals["total_outflow_mm"]
        surf_store = series[-1]["surface_storage_mm"]
        residual = rain - interc - infil - surf_store - outflow
        tol = max(rain * 0.01, 0.1)
        assert abs(residual) < tol, (
            f"Mass balance residual {residual:.4f} mm (rain={rain:.2f}, "
            f"interc={interc:.2f}, infil={infil:.2f}, "
            f"surf={surf_store:.2f}, out={outflow:.2f})"
        )

    def test_timeseries_mass_balance(self, simulation_output):
        """Mass balance should be reasonable throughout the simulation."""
        _, series, _ = simulation_output
        for rec in series[10:]:
            if rec["rainfall_mm"] > 0.1:
                assert abs(rec["mass_balance_error_pct"]) < 2.0, (
                    f"Mass balance error {rec['mass_balance_error_pct']:.4f}% "
                    f"at t={rec['time_min']:.1f} min"
                )


# ---------------------------------------------------------------------------
# Physical plausibility
# ---------------------------------------------------------------------------
class TestPhysicalPlausibility:
    def test_runoff_coefficient_range(self, simulation_output):
        totals, _, _ = simulation_output
        rc = totals["runoff_coefficient"]
        assert 0.05 < rc < 0.95, f"Runoff coefficient {rc:.4f} outside plausible range"

    def test_interception_positive(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["total_interception_mm"] > 0

    def test_interception_less_than_rainfall(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["total_interception_mm"] < totals["total_rainfall_mm"]

    def test_interception_bounded_by_max_capacity(self, simulation_output, lc_params):
        totals, _, _ = simulation_output
        max_smax = max(p["canopy_storage_mm"] for p in lc_params.values())
        assert totals["total_interception_mm"] <= max_smax + 0.5, (
            f"Interception {totals['total_interception_mm']:.2f} exceeds "
            f"max canopy storage {max_smax}"
        )

    def test_infiltration_positive(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["total_infiltration_mm"] > 0

    def test_infiltration_less_than_rainfall(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["total_infiltration_mm"] < totals["total_rainfall_mm"]

    def test_outflow_positive(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["total_outflow_mm"] > 0

    def test_peak_discharge_positive(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["peak_discharge_m3s"] > 0

    def test_peak_time_after_peak_rainfall(self, simulation_output):
        """Peak rainfall is at t=30 min; peak discharge must lag behind."""
        totals, _, _ = simulation_output
        assert totals["peak_time_min"] >= 30.0, (
            f"Peak discharge at {totals['peak_time_min']:.1f} min "
            "should not precede peak rainfall at 30 min"
        )

    def test_peak_time_within_simulation(self, simulation_output):
        totals, _, _ = simulation_output
        assert totals["peak_time_min"] <= 120.0

    def test_values_non_negative(self, simulation_output):
        totals, _, _ = simulation_output
        for key in [
            "total_rainfall_mm",
            "total_interception_mm",
            "total_infiltration_mm",
            "total_outflow_mm",
            "peak_discharge_m3s",
            "runoff_coefficient",
        ]:
            assert totals[key] >= 0, f"{key} = {totals[key]} should be non-negative"


# ---------------------------------------------------------------------------
# Hydrograph properties
# ---------------------------------------------------------------------------
class TestHydrograph:
    def test_has_clear_peak(self, simulation_output):
        _, _, hydro = simulation_output
        discharges = [r["discharge_m3s"] for r in hydro]
        peak = max(discharges)
        assert peak > 0

    def test_recession_occurs(self, simulation_output):
        """Discharge should decrease significantly by end of simulation."""
        _, _, hydro = simulation_output
        peak = max(r["discharge_m3s"] for r in hydro)
        last_vals = [r["discharge_m3s"] for r in hydro[-10:]]
        assert max(last_vals) < peak * 0.5, (
            "Discharge should recede to < 50% of peak by end of simulation"
        )

    def test_starts_near_zero(self, simulation_output):
        _, _, hydro = simulation_output
        assert hydro[0]["discharge_m3s"] < 0.001

    def test_sufficient_timesteps(self, simulation_output):
        _, _, hydro = simulation_output
        assert len(hydro) >= 200, f"Expected >= 200 timesteps, got {len(hydro)}"

    def test_hydrograph_peak_magnitude_plausible(self, simulation_output, dem_data):
        """Peak discharge should be physically plausible for this catchment."""
        _, _, hydro = simulation_output
        header, _ = dem_data
        area = header["nrows"] * header["ncols"] * header["cellsize"] ** 2
        peak = max(r["discharge_m3s"] for r in hydro)
        assert 0.001 < peak < 2.0, (
            f"Peak discharge {peak:.4f} m3/s outside plausible range "
            f"for catchment area {area:.0f} m2"
        )


# ---------------------------------------------------------------------------
# Time series monotonicity and consistency
# ---------------------------------------------------------------------------
class TestTimeseries:
    def test_cumulative_rainfall_monotonic(self, simulation_output):
        _, series, _ = simulation_output
        prev = -1e-6
        for rec in series:
            assert rec["rainfall_mm"] >= prev - 1e-6
            prev = rec["rainfall_mm"]

    def test_cumulative_infiltration_monotonic(self, simulation_output):
        _, series, _ = simulation_output
        prev = -1e-6
        for rec in series:
            assert rec["infiltration_mm"] >= prev - 1e-6
            prev = rec["infiltration_mm"]

    def test_cumulative_interception_monotonic(self, simulation_output):
        _, series, _ = simulation_output
        prev = -1e-6
        for rec in series:
            assert rec["interception_mm"] >= prev - 1e-6
            prev = rec["interception_mm"]

    def test_cumulative_outflow_monotonic(self, simulation_output):
        _, series, _ = simulation_output
        prev = -1e-6
        for rec in series:
            assert rec["outflow_mm"] >= prev - 1e-6
            prev = rec["outflow_mm"]

    def test_surface_storage_non_negative(self, simulation_output):
        _, series, _ = simulation_output
        for rec in series:
            assert rec["surface_storage_mm"] >= -0.01, (
                f"Surface storage {rec['surface_storage_mm']:.4f} at "
                f"t={rec['time_min']} is negative"
            )

    def test_final_surface_storage_small(self, simulation_output):
        """After rain stops (t=65), surface storage should drain significantly."""
        totals, series, _ = simulation_output
        last_store = series[-1]["surface_storage_mm"]
        rain = totals["total_rainfall_mm"]
        assert last_store < rain * 0.3, (
            f"Final surface storage {last_store:.2f} mm is too high "
            f"relative to rainfall {rain:.2f} mm"
        )


# ---------------------------------------------------------------------------
# Infiltration behavior
# ---------------------------------------------------------------------------
class TestInfiltrationBehavior:
    def test_infiltration_rate_decreases(self, simulation_output):
        """Infiltration rate should generally decrease during ponded conditions."""
        _, series, _ = simulation_output
        n = len(series)
        if n < 40:
            pytest.skip("Too few timesteps to test infiltration rate trend")

        window = max(1, n // 10)
        early_rate = (
            series[2 * window]["infiltration_mm"] - series[window]["infiltration_mm"]
        ) / window
        later_rate = (
            series[4 * window]["infiltration_mm"] - series[3 * window]["infiltration_mm"]
        ) / window

        assert later_rate <= early_rate * 1.5, (
            f"Later infiltration rate ({later_rate:.4f}) unexpectedly exceeds "
            f"early rate ({early_rate:.4f})"
        )

    def test_ponding_produces_runoff(self, simulation_output):
        """With peak rain exceeding soil Ksat, ponding must occur."""
        totals, _, _ = simulation_output
        assert totals["total_outflow_mm"] > 1.0, (
            "Expected significant runoff given rainfall intensity exceeds Ksat"
        )
