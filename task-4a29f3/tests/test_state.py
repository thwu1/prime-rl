"""Tests for Land Surface Temperature quality assessment and correction."""


import pytest
import numpy as np
import json
import os
from osgeo import gdal, osr

gdal.UseExceptions()


# ---------------------------------------------------------------------------
# Reference computation helpers
# ---------------------------------------------------------------------------

def read_band(filepath):
    ds = gdal.Open(filepath)
    assert ds is not None, f"Cannot open {filepath}"
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray()
    nodata = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    w, h = ds.RasterXSize, ds.RasterYSize
    ds = None
    return data, nodata, gt, proj, w, h


def ref_mask(qa):
    fill = (qa & (1 << 0)) != 0
    cloud = (qa & (1 << 3)) != 0
    shadow = (qa & (1 << 4)) != 0
    snow = (qa & (1 << 5)) != 0
    return ~(fill | cloud | shadow | snow)


def ref_ndvi(red, nir):
    with np.errstate(divide='ignore', invalid='ignore'):
        return (nir.astype(np.float64) - red.astype(np.float64)) / \
               (nir.astype(np.float64) + red.astype(np.float64))


def ref_emissivity(ndvi):
    eps_s, eps_v, C = 0.964, 0.984, 0.005
    ndvi_s, ndvi_v = 0.2, 0.5
    e = np.full_like(ndvi, np.nan, dtype=np.float64)
    e[ndvi < 0] = 0.991
    e[(ndvi >= 0) & (ndvi < ndvi_s)] = eps_s
    e[ndvi > ndvi_v] = eps_v + C
    m = (ndvi >= ndvi_s) & (ndvi <= ndvi_v)
    Pv = ((ndvi[m] - ndvi_s) / (ndvi_v - ndvi_s)) ** 2
    e[m] = eps_v * Pv + eps_s * (1 - Pv) + C
    return e


def ref_lst(thermal_dn, emissivity, mtl):
    p = mtl["LANDSAT_METADATA_FILE"]
    M_L = p["LEVEL1_RADIOMETRIC_RESCALING"]["RADIANCE_MULT_BAND_10"]
    A_L = p["LEVEL1_RADIOMETRIC_RESCALING"]["RADIANCE_ADD_BAND_10"]
    K1 = p["LEVEL1_THERMAL_CONSTANTS"]["K1_CONSTANT_BAND_10"]
    K2 = p["LEVEL1_THERMAL_CONSTANTS"]["K2_CONSTANT_BAND_10"]
    wl = p["TIRS_THERMAL_CONSTANTS"]["BAND_10_CENTRAL_WAVELENGTH_UM"]
    rho = 14388.0
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        rad = M_L * thermal_dn.astype(np.float64) + A_L
        bt_k = K2 / np.log(K1 / rad + 1)
        lst_k = bt_k / (1 + (wl * bt_k / rho) * np.log(emissivity))
    return lst_k - 273.15


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def src():
    red, _, gt, proj, w, h = read_band('/app/data/LC08_B4_RED.tif')
    nir, _, _, _, _, _ = read_band('/app/data/LC08_B5_NIR.tif')
    thermal, _, _, _, _, _ = read_band('/app/data/LC08_B10_THERMAL.tif')
    qa, _, _, _, _, _ = read_band('/app/data/LC08_QA_PIXEL.tif')
    with open('/app/data/LC08_MTL.json') as f:
        mtl = json.load(f)
    return dict(red=red, nir=nir, thermal=thermal, qa=qa, mtl=mtl, gt=gt, proj=proj)


@pytest.fixture(scope="module")
def reference(src):
    mask = ref_mask(src['qa'])
    ndvi = ref_ndvi(src['red'], src['nir'])
    emissivity = ref_emissivity(ndvi)
    lst = ref_lst(src['thermal'], emissivity, src['mtl'])
    return dict(mask=mask, ndvi=ndvi, emissivity=emissivity, lst=lst)


@pytest.fixture(scope="module")
def out():
    result = {}
    for name in ['valid_mask', 'ndvi', 'emissivity', 'lst_celsius']:
        path = f'/app/output/{name}.tif'
        data, nodata, gt, proj, w, h = read_band(path)
        result[name] = dict(data=data, nodata=nodata, gt=gt, proj=proj, w=w, h=h)
    return result


# ---------------------------------------------------------------------------
# Test: Output files exist and have correct structure
# ---------------------------------------------------------------------------

class TestOutputFiles:
    def test_all_files_exist(self):
        for f in ['valid_mask.tif', 'ndvi.tif', 'emissivity.tif',
                   'lst_celsius.tif', 'zonal_stats.json', 'diagnostic_report.json']:
            assert os.path.exists(f'/app/output/{f}'), f"Missing output: {f}"

    def test_dimensions(self, out):
        for name in ['valid_mask', 'ndvi', 'emissivity', 'lst_celsius']:
            assert out[name]['w'] == 200, f"{name} width != 200"
            assert out[name]['h'] == 200, f"{name} height != 200"

    def test_crs(self, out):
        target = osr.SpatialReference()
        target.ImportFromEPSG(32618)
        for name in ['valid_mask', 'ndvi', 'emissivity', 'lst_celsius']:
            srs = osr.SpatialReference(wkt=out[name]['proj'])
            assert srs.IsSame(target), f"{name} CRS is not EPSG:32618"


# ---------------------------------------------------------------------------
# Test: Cloud / quality mask
# ---------------------------------------------------------------------------

class TestCloudMask:
    def test_mask_binary(self, out):
        d = out['valid_mask']['data']
        uniq = set(np.unique(d).tolist())
        assert uniq.issubset({0, 1, 0.0, 1.0}), f"Non-binary mask values: {uniq}"

    def test_cloud_pixels_masked(self, out):
        assert np.all(out['valid_mask']['data'][30:50, 60:85] == 0)

    def test_shadow_pixels_masked(self, out):
        assert np.all(out['valid_mask']['data'][50:65, 75:100] == 0)

    def test_fill_edges_masked(self, out):
        d = out['valid_mask']['data']
        assert np.all(d[0:3, :] == 0)
        assert np.all(d[-3:, :] == 0)
        assert np.all(d[:, 0:3] == 0)
        assert np.all(d[:, -3:] == 0)

    def test_snow_pixels_masked(self, out):
        assert np.all(out['valid_mask']['data'][170:180, 170:180] == 0)

    def test_clear_pixels_valid(self, out):
        d = out['valid_mask']['data']
        assert d[20, 20] == 1, "Clear forest pixel should be 1"
        assert d[50, 150] == 1, "Clear urban pixel should be 1"

    def test_mask_matches_reference(self, out, reference):
        out_m = out['valid_mask']['data'].astype(np.uint8)
        ref_m = reference['mask'].astype(np.uint8)
        agreement = np.mean(out_m == ref_m)
        assert agreement > 0.99, f"Mask agreement {agreement:.4f} < 0.99"


# ---------------------------------------------------------------------------
# Test: NDVI
# ---------------------------------------------------------------------------

class TestNDVI:
    def test_range(self, out):
        d = out['ndvi']['data']
        m = out['valid_mask']['data']
        v = d[(m == 1) & ~np.isnan(d)]
        assert len(v) > 0
        assert np.all(v >= -1.0) and np.all(v <= 1.0)

    def test_forest_high(self, out):
        v = out['ndvi']['data'][15:25, 15:25]
        v = v[~np.isnan(v)]
        assert np.mean(v) > 0.70, f"Forest NDVI {np.mean(v):.3f} < 0.70"

    def test_water_low(self, out):
        v = out['ndvi']['data'][150:160, 150:160]
        v = v[~np.isnan(v)]
        assert np.mean(v) < 0.1, f"Water NDVI {np.mean(v):.3f} >= 0.1"

    def test_reference(self, out, reference):
        o = out['ndvi']['data']
        m = out['valid_mask']['data']
        r = reference['ndvi']
        valid = (m == 1) & ~np.isnan(o) & ~np.isnan(r)
        np.testing.assert_allclose(o[valid], r[valid].astype(np.float32), atol=0.01)


# ---------------------------------------------------------------------------
# Test: Emissivity
# ---------------------------------------------------------------------------

class TestEmissivity:
    def test_range(self, out):
        d = out['emissivity']['data']
        m = out['valid_mask']['data']
        v = d[(m == 1) & ~np.isnan(d)]
        assert len(v) > 0
        assert np.all(v >= 0.9) and np.all(v <= 1.0)

    def test_not_spatially_uniform(self, out):
        d = out['emissivity']['data']
        m = out['valid_mask']['data']
        v = d[(m == 1) & ~np.isnan(d)]
        assert np.std(v) > 0.005, \
            f"Emissivity std={np.std(v):.6f} too low — should vary by land cover"

    def test_forest_high(self, out):
        v = out['emissivity']['data'][15:25, 15:25]
        v = v[~np.isnan(v)]
        assert np.mean(v) > 0.985, f"Forest emissivity {np.mean(v):.4f}"

    def test_reference(self, out, reference):
        o = out['emissivity']['data']
        m = out['valid_mask']['data']
        r = reference['emissivity']
        valid = (m == 1) & ~np.isnan(o) & ~np.isnan(r)
        np.testing.assert_allclose(o[valid], r[valid].astype(np.float32), atol=0.005)


# ---------------------------------------------------------------------------
# Test: Land Surface Temperature
# ---------------------------------------------------------------------------

class TestLST:
    def test_range(self, out):
        d = out['lst_celsius']['data']
        m = out['valid_mask']['data']
        v = d[(m == 1) & ~np.isnan(d)]
        assert len(v) > 0
        assert np.all(v >= -10), f"Min LST {v.min():.1f}"
        assert np.all(v <= 60), f"Max LST {v.max():.1f}"

    def test_urban_hotter_than_forest(self, out):
        lst = out['lst_celsius']['data']
        m = out['valid_mask']['data']

        fz = np.zeros_like(m, dtype=bool)
        fz[10:80, 10:80] = True
        fv = fz & (m == 1) & ~np.isnan(lst)

        uz = np.zeros_like(m, dtype=bool)
        uz[10:80, 120:190] = True
        uv = uz & (m == 1) & ~np.isnan(lst)

        assert np.mean(lst[uv]) > np.mean(lst[fv]) + 5, \
            f"Urban {np.mean(lst[uv]):.1f} not >5C warmer than forest {np.mean(lst[fv]):.1f}"

    def test_masked_pixels_nan(self, out):
        lst = out['lst_celsius']['data']
        m = out['valid_mask']['data']
        nd = out['lst_celsius']['nodata']
        invalid = m == 0
        if nd is not None and not np.isnan(nd):
            ok = np.isnan(lst[invalid]) | (lst[invalid] == nd)
        else:
            ok = np.isnan(lst[invalid])
        assert np.all(ok), "Some masked pixels have real LST values"

    def test_reference(self, out, reference):
        o = out['lst_celsius']['data']
        m = out['valid_mask']['data']
        r = reference['lst']
        valid = (m == 1) & ~np.isnan(o) & ~np.isnan(r)
        np.testing.assert_allclose(o[valid], r[valid].astype(np.float32), atol=0.5)


# ---------------------------------------------------------------------------
# Test: Zonal statistics
# ---------------------------------------------------------------------------

class TestZonalStats:
    def test_json_format(self):
        with open('/app/output/zonal_stats.json') as f:
            s = json.load(f)
        for zone in ['forest', 'urban', 'agriculture']:
            assert zone in s, f"Missing zone: {zone}"
            for k in ['mean_lst_celsius', 'min_lst_celsius',
                       'max_lst_celsius', 'valid_pixel_count']:
                assert k in s[zone], f"Missing key {k} in {zone}"

    def test_forest_range(self):
        with open('/app/output/zonal_stats.json') as f:
            s = json.load(f)
        assert 18 < s['forest']['mean_lst_celsius'] < 35
        assert s['forest']['valid_pixel_count'] < 4900
        assert s['forest']['valid_pixel_count'] > 3000

    def test_urban_range(self):
        with open('/app/output/zonal_stats.json') as f:
            s = json.load(f)
        assert 30 < s['urban']['mean_lst_celsius'] < 50

    def test_urban_hotter_than_forest(self):
        with open('/app/output/zonal_stats.json') as f:
            s = json.load(f)
        assert s['urban']['mean_lst_celsius'] > s['forest']['mean_lst_celsius']

    def test_agriculture_range(self):
        with open('/app/output/zonal_stats.json') as f:
            s = json.load(f)
        assert 25 < s['agriculture']['mean_lst_celsius'] < 40

    def test_zonal_reference(self, reference):
        with open('/app/output/zonal_stats.json') as f:
            out_s = json.load(f)

        rmask = reference['mask']
        rlst = reference['lst']

        zones = {
            'forest': (slice(10, 80), slice(10, 80)),
            'urban': (slice(10, 80), slice(120, 190)),
            'agriculture': (slice(120, 190), slice(10, 80)),
        }

        for name, (rs, cs) in zones.items():
            z = np.zeros_like(rmask, dtype=bool)
            z[rs, cs] = True
            vz = z & rmask & ~np.isnan(rlst)

            r_mean = float(np.mean(rlst[vz]))
            r_count = int(vz.sum())

            assert abs(out_s[name]['mean_lst_celsius'] - r_mean) < 2.0, \
                f"{name} mean: {out_s[name]['mean_lst_celsius']:.2f} vs ref {r_mean:.2f}"
            assert abs(out_s[name]['valid_pixel_count'] - r_count) <= 50, \
                f"{name} count: {out_s[name]['valid_pixel_count']} vs ref {r_count}"


# ---------------------------------------------------------------------------
# Test: Diagnostic report
# ---------------------------------------------------------------------------

class TestDiagnosticReport:
    def test_report_valid_json(self):
        with open('/app/output/diagnostic_report.json') as f:
            report = json.load(f)
        assert isinstance(report, dict)

    def test_report_has_errors_found(self):
        with open('/app/output/diagnostic_report.json') as f:
            report = json.load(f)
        assert 'errors_found' in report
        assert isinstance(report['errors_found'], list)
        assert len(report['errors_found']) >= 2, \
            f"Expected at least 2 errors identified, got {len(report['errors_found'])}"

    def test_report_has_corrections(self):
        with open('/app/output/diagnostic_report.json') as f:
            report = json.load(f)
        assert 'corrections_applied' in report
        assert isinstance(report['corrections_applied'], list)
        assert len(report['corrections_applied']) >= 2

    def test_identifies_masking_issue(self):
        with open('/app/output/diagnostic_report.json') as f:
            report = json.load(f)
        text = json.dumps(report).lower()
        mask_terms = ['mask', 'qa', 'quality', 'cloud', 'shadow', 'fill',
                      'snow', 'bit', 'flag', 'pixel']
        assert any(t in text for t in mask_terms), \
            "Diagnostic report should identify masking/QA quality issues"

    def test_identifies_emissivity_issue(self):
        with open('/app/output/diagnostic_report.json') as f:
            report = json.load(f)
        text = json.dumps(report).lower()
        emis_terms = ['emissivity', 'emissi', 'uniform', 'constant', 'flat',
                      'surface property', 'land cover', 'ndvi']
        assert any(t in text for t in emis_terms), \
            "Diagnostic report should identify emissivity estimation issues"
