"""Tests for LiDAR terrain analysis pipeline outputs."""

import base64
import json
import os
import struct
import subprocess
import zlib

import numpy as np
import pytest

OUTPUT_DIR = "/app/output"

# Encoded DTM validation reference: 96 sample points (x, y, true_z)
# on a 10x10 grid (10m inset), excluding building footprint area.
# compressed with zlib + base64 — prevents trivial extraction
_VR = (
    "eNpV1XtMU2cYx/FKyYCtMqAbQaQLs2UDtmpBmJ0b2UHXIdUxCTY9p5hMWIE5AqSsmiKz"
    "A+Re7ehEImjACwKpjajjUtRtBMm6i7DuxnBiYHIbTJhNpnFcmr3p9pyn/avJN6fv+/uk"
    "JymHw+HcKH8ukXz0G6JTE+deeTHiKq2iOP/3V42TujrSe+/mcUdOMWwvDLPFnCD9mfiK"
    "QbGTZvtFs3m+kfStiTkZJ6ewT0mN55tJ5ycF24Ki8Zwwm2bvedI/j30+s/QQdoVC8WwH"
    "6S2CSp6lH7txUjpsIb3g11hDWRDutGnCqq6QbrRuF3+Tip18UD2kL8tkf3RHqijyfaNP"
    "BXqrM8++3PItdvCK/R1VlgTs4J0x5VLeFobt4A31rjozsR87eD/YaU3W12IH7wt7rM7f"
    "72MHL++WvuXPTLwXvJKpotsR/djB++ERf2f1iIfL5d20X/SQU6OiyH1haW7eCuWl2rle"
    "7OAtXJQpuLXYwbuj88K2qADs4J1t50pNhxm2g3e8cSXSX4EdvF7Jfh2Bd7CDt5OfMxJ0"
    "Gc8Hr4lbs2damM528D549Npi9JyHy+Xlm7MKdqepKLLP3OzmXSls8mrNxw5eRpsxFBeA"
    "HbymBJ49lvxe0MGbsPySz+Vw7ODNKLfnlQuwg9db8NSTShN28E445Pdux+O94DWrHH0b"
    "mrGD95juL8dPRz1cLu8x89qG2fUqinik825e/WpyUtcMw3bw3v/6YHBtFHbwbsg1y4cN"
    "NNvBe0Cbv3SoEDt4r687nh9jxQ7eL1b+tpX54vngDdmSrX03BTt4l9R9auEZ7OBt2Gdq"
    "tYwz7i6Xd0XXOvhzD0OR52zxlehNulkSd3wtdvDuUtav1pXSbAevoODTBdEDJdthf0hT"
    "o3x0Ez4P+2Pvpop+bMMO+6no7ytk3ngv7O8eiCu+s85jp2t/8Oiu0tPf0RQ5V1Hqtn+s"
    "42S3JB077NcHDi03iLHDfn2kV6D9MyXbYT9fesDA6LHD/o9Szona0/Ac2G8Tbv7BYMMO"
    "+/t2HoyoO+qx07Vf/aVJW/xISZH3YPKW2/6RnNPTGSqa7bBftvDmwJplfB72z5e8lXdT"
    "ix3et/fqc+t5POzwvsluGOgmP+zg9av5pT3oMHbwLsVMf9UajnvAe/WdSrqrGjt4z8oT"
    "xJt1tLvL5S2ScUVOH5oiuzUhVeiVZpUpFTPYwbvGnv3GRCR28PLy/a4EGpRsB2/T+zO2"
    "VQ128M5KVscWerGD93VxsVDoi+eD95o15J+ut7GDN3UsdH1OC3bwppekJUnGPVwub0rb"
    "UJap57//a7WbN9Rw6VTMEYbt4FWeq7eHP8bnwbvY3LvFkY0dvB8PPHEtXogdvIO/yc37"
    "tmEHryZq42PdBezg5Xp1+qoFuAe8bZn84YBi7ODduLfo+ugnjLvL5ZU4tz99j2KofwGo"
    "qYmn"
)


def _load_validation_points():
    """Decode pre-computed validation reference points."""
    raw = zlib.decompress(base64.b64decode(_VR))
    n_pts = len(raw) // 24  # 3 doubles per point
    pts = []
    for i in range(n_pts):
        x, y, z = struct.unpack_from('<3d', raw, i * 24)
        pts.append((x, y, z))
    return pts


def _gdal_info(path):
    """Run gdalinfo -json and return parsed dict."""
    r = subprocess.run(["gdalinfo", "-json", path],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"gdalinfo failed on {path}: {r.stderr}"
    return json.loads(r.stdout)


def _read_band(path, band_idx=1):
    """Read a single GeoTIFF band via osgeo.gdal."""
    from osgeo import gdal
    ds = gdal.Open(path)
    assert ds is not None, f"Cannot open {path}"
    band = ds.GetRasterBand(band_idx)
    arr = band.ReadAsArray().astype(np.float64)
    nodata = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    srs_wkt = ds.GetProjection()
    ds = None
    return arr, nodata, gt, srs_wkt


# ── File existence ────────────────────────────────────────────


class TestFileExistence:
    def test_process_sh(self):
        assert os.path.exists("/app/process.sh"), "process.sh not found"

    def test_ground_las(self):
        found = (os.path.exists(f"{OUTPUT_DIR}/ground.las")
                 or os.path.exists(f"{OUTPUT_DIR}/ground.laz"))
        assert found, "ground.las (or .laz) not found"

    def test_non_ground_las(self):
        found = (os.path.exists(f"{OUTPUT_DIR}/non_ground.las")
                 or os.path.exists(f"{OUTPUT_DIR}/non_ground.laz"))
        assert found, "non_ground.las (or .laz) not found"

    def test_dtm_tif(self):
        assert os.path.exists(f"{OUTPUT_DIR}/dtm.tif")

    def test_chm_tif(self):
        assert os.path.exists(f"{OUTPUT_DIR}/chm.tif")

    def test_slope_tif(self):
        assert os.path.exists(f"{OUTPUT_DIR}/slope.tif")

    def test_report_json(self):
        assert os.path.exists(f"{OUTPUT_DIR}/report.json")


# ── DTM validation ────────────────────────────────────────────


class TestDTM:
    def test_valid_geotiff(self):
        info = _gdal_info(f"{OUTPUT_DIR}/dtm.tif")
        assert "size" in info

    def test_crs_utm_18n(self):
        _, _, _, srs_wkt = _read_band(f"{OUTPUT_DIR}/dtm.tif")
        assert srs_wkt, "DTM has no CRS"
        check = ("UTM" in srs_wkt or "32618" in srs_wkt
                 or "Transverse_Mercator" in srs_wkt)
        assert check, f"DTM CRS is not UTM 18N: {srs_wkt[:120]}"

    def test_resolution_approx_1m(self):
        _, _, gt, _ = _read_band(f"{OUTPUT_DIR}/dtm.tif")
        assert abs(gt[1] - 1.0) < 0.5, f"X pixel size {gt[1]}, expected ~1.0"
        assert abs(abs(gt[5]) - 1.0) < 0.5, f"Y pixel size {gt[5]}, expected ~-1.0"

    def test_elevation_range(self):
        arr, nodata, _, _ = _read_band(f"{OUTPUT_DIR}/dtm.tif")
        valid = arr.ravel()
        if nodata is not None:
            valid = valid[~np.isclose(valid, nodata, atol=0.1)]
        valid = valid[~np.isnan(valid)]
        assert len(valid) > 100, "DTM has too few valid cells"
        assert np.min(valid) > 85, f"DTM min {np.min(valid):.1f} < 85"
        assert np.max(valid) < 120, f"DTM max {np.max(valid):.1f} > 120"

    def test_dtm_accuracy(self):
        """RMSE of DTM against encoded validation points < 2.0 m."""
        arr, nodata, gt, _ = _read_band(f"{OUTPUT_DIR}/dtm.tif")
        rows, cols = arr.shape
        val_pts = _load_validation_points()
        errors = []
        for vx, vy, true_z in val_pts:
            # Map world coords to raster pixel
            c = int((vx - gt[0]) / gt[1])
            r = int((vy - gt[3]) / gt[5])
            if r < 0 or r >= rows or c < 0 or c >= cols:
                continue
            val = arr[r, c]
            if nodata is not None and np.isclose(val, nodata, atol=0.1):
                continue
            if np.isnan(val):
                continue
            errors.append((val - true_z) ** 2)
        assert len(errors) > 50, "Too few DTM samples for accuracy check"
        rmse = np.sqrt(np.mean(errors))
        assert rmse < 2.0, f"DTM RMSE = {rmse:.3f} m, expected < 2.0"

    def test_no_large_nodata_holes(self):
        """At least 80% of cells within the survey area should have values."""
        arr, nodata, gt, _ = _read_band(f"{OUTPUT_DIR}/dtm.tif")
        rows, cols = arr.shape
        valid_count, total_count = 0, 0
        origin_x, origin_y = 500000.0, 4500000.0
        area = 200.0
        for r in range(rows):
            for c in range(cols):
                x = gt[0] + (c + 0.5) * gt[1]
                y = gt[3] + (r + 0.5) * gt[5]
                if (origin_x + 5 < x < origin_x + area - 5
                        and origin_y + 5 < y < origin_y + area - 5):
                    total_count += 1
                    val = arr[r, c]
                    is_valid = True
                    if np.isnan(val):
                        is_valid = False
                    elif nodata is not None and np.isclose(val, nodata, atol=0.1):
                        is_valid = False
                    if is_valid:
                        valid_count += 1
        if total_count > 0:
            frac = valid_count / total_count
            assert frac > 0.80, (
                f"Only {frac*100:.1f}% of DTM cells have data; expected >80%"
            )


# ── CHM validation ────────────────────────────────────────────


class TestCHM:
    def test_valid_geotiff(self):
        info = _gdal_info(f"{OUTPUT_DIR}/chm.tif")
        assert "size" in info

    def test_non_negative(self):
        arr, nodata, _, _ = _read_band(f"{OUTPUT_DIR}/chm.tif")
        valid = arr.ravel()
        if nodata is not None:
            valid = valid[~np.isclose(valid, nodata, atol=0.1)]
        valid = valid[~np.isnan(valid)]
        assert np.min(valid) >= -0.5, f"CHM min {np.min(valid):.2f} < -0.5"

    def test_max_height_range(self):
        arr, nodata, _, _ = _read_band(f"{OUTPUT_DIR}/chm.tif")
        valid = arr.ravel()
        if nodata is not None:
            valid = valid[~np.isclose(valid, nodata, atol=0.1)]
        valid = valid[~np.isnan(valid)]
        mx = np.max(valid)
        assert 3.0 < mx < 30.0, f"CHM max height {mx:.1f} not in (3, 30)"


# ── Slope validation ──────────────────────────────────────────


class TestSlope:
    def test_valid_geotiff(self):
        info = _gdal_info(f"{OUTPUT_DIR}/slope.tif")
        assert "size" in info

    def test_slope_range(self):
        arr, nodata, _, _ = _read_band(f"{OUTPUT_DIR}/slope.tif")
        valid = arr.ravel()
        if nodata is not None:
            valid = valid[~np.isclose(valid, nodata, atol=0.1)]
        valid = valid[~np.isnan(valid)]
        assert len(valid) > 10, "Slope raster has too few valid cells"
        assert np.min(valid) >= 0, f"Slope min {np.min(valid):.2f} < 0"
        assert np.max(valid) < 60, f"Slope max {np.max(valid):.1f} >= 60 deg"


# ── Report validation ─────────────────────────────────────────


class TestReport:
    @pytest.fixture(autouse=True)
    def _load(self):
        with open(f"{OUTPUT_DIR}/report.json") as f:
            self.report = json.load(f)

    def test_required_top_level_keys(self):
        for key in ("total_points", "noise_points_removed",
                     "ground_points", "non_ground_points",
                     "bounding_box", "dtm", "chm", "slope"):
            assert key in self.report, f"Missing key: {key}"

    def test_total_points(self):
        tp = self.report["total_points"]
        assert 50000 < tp < 80000, f"total_points={tp} outside (50k,80k)"

    def test_noise_detected(self):
        nr = self.report["noise_points_removed"]
        assert nr > 100, f"noise_points_removed={nr}, expected >100"

    def test_ground_points_count(self):
        gp = self.report["ground_points"]
        assert 10000 < gp < 60000, f"ground_points={gp} outside (10k,60k)"

    def test_bounding_box(self):
        bb = self.report["bounding_box"]
        for k in ("minx", "maxx", "miny", "maxy", "minz", "maxz"):
            assert k in bb, f"Missing bounding_box key: {k}"
        assert 499990 < bb["minx"] < 500010
        assert 500190 < bb["maxx"] < 500210
        assert 4499990 < bb["miny"] < 4500010
        assert 4500190 < bb["maxy"] < 4500210

    def test_dtm_section(self):
        dtm = self.report["dtm"]
        assert dtm["crs"] == "EPSG:32618"
        assert 85 < dtm["min"] < 100
        assert 100 < dtm["max"] < 120
        assert dtm["width_pixels"] > 50
        assert dtm["height_pixels"] > 50

    def test_chm_section(self):
        chm = self.report["chm"]
        assert chm["max_height"] > 3.0
        assert 0 <= chm["vegetation_coverage_pct"] <= 100

    def test_slope_section(self):
        sl = self.report["slope"]
        assert "max_degrees" in sl
        assert "mean_degrees" in sl
        assert sl["max_degrees"] > 0
        assert sl["mean_degrees"] > 0


# ── Ground classification quality ─────────────────────────────


class TestGroundClassification:
    def test_ground_file_has_reasonable_count(self):
        """ground.las should contain between 10k and 60k ground points."""
        import laspy
        ground_path = f"{OUTPUT_DIR}/ground.las"
        if not os.path.exists(ground_path):
            ground_path = f"{OUTPUT_DIR}/ground.laz"
        las = laspy.read(ground_path)
        n = len(las.points)
        assert 10000 < n < 60000, (
            f"ground file has {n} points, expected 10k-60k"
        )
