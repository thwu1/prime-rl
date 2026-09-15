"""Tests for terrain suitability assessment with data quality audit.

"""

import csv
import json
import os
import numpy as np
import pytest
from osgeo import gdal, osr, ogr
from scipy import ndimage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def spec():
    with open('/app/site_spec.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dem_calibrated_info():
    ds = gdal.Open('/app/output/dem_calibrated.tif')
    assert ds is not None, "Cannot open /app/output/dem_calibrated.tif"
    gt = ds.GetGeoTransform()
    ny = ds.RasterYSize
    nx = ds.RasterXSize
    dem = ds.GetRasterBand(1).ReadAsArray()
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    proj = ds.GetProjection()
    ds = None
    return {'gt': gt, 'ny': ny, 'nx': nx, 'dem': dem,
            'nodata': nodata, 'proj': proj}


@pytest.fixture(scope="module")
def dem_raw_arr():
    ds = gdal.Open('/app/dem.tif')
    assert ds is not None
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


@pytest.fixture(scope="module")
def results():
    with open('/app/results.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def slope_arr():
    ds = gdal.Open('/app/output/slope.tif')
    assert ds is not None
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


@pytest.fixture(scope="module")
def aspect_arr():
    ds = gdal.Open('/app/output/aspect.tif')
    assert ds is not None
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


@pytest.fixture(scope="module")
def tri_arr():
    ds = gdal.Open('/app/output/tri.tif')
    assert ds is not None
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


@pytest.fixture(scope="module")
def suit_arr():
    ds = gdal.Open('/app/output/suitability.tif')
    assert ds is not None
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


@pytest.fixture(scope="module")
def control_points():
    pts = []
    with open('/app/control_points.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pts.append({
                'id': int(row['id']),
                'easting': float(row['easting']),
                'northing': float(row['northing']),
                'elevation_m': float(row['elevation_m']),
            })
    return pts


# ---------------------------------------------------------------------------
# 1. Output files exist
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    @pytest.mark.parametrize("path", [
        '/app/output/dem_calibrated.tif',
        '/app/output/slope.tif',
        '/app/output/aspect.tif',
        '/app/output/tri.tif',
        '/app/output/suitability.tif',
        '/app/results.json',
    ])
    def test_file_exists(self, path):
        assert os.path.isfile(path), f"Missing output: {path}"


# ---------------------------------------------------------------------------
# 2. DEM calibration — vertical bias must be corrected
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_control_points_match(self, dem_calibrated_info, control_points):
        gt = dem_calibrated_info['gt']
        dem = dem_calibrated_info['dem']
        nodata = dem_calibrated_info['nodata']

        residuals = []
        for cp in control_points:
            col = int((cp['easting'] - gt[0]) / gt[1])
            row = int((cp['northing'] - gt[3]) / gt[5])
            val = float(dem[row, col])

            if nodata is not None and val == nodata:
                continue
            if np.isnan(val):
                continue

            residual = abs(val - cp['elevation_m'])
            residuals.append(residual)
            assert residual < 2.0, (
                f"Control point {cp['id']}: calibrated DEM value "
                f"{val:.2f} vs true {cp['elevation_m']:.2f} "
                f"(residual {residual:.2f} m)"
            )

        assert len(residuals) >= 15, (
            f"Only {len(residuals)} valid control point comparisons"
        )
        assert np.mean(residuals) < 1.0, (
            f"Mean control point residual {np.mean(residuals):.2f} m too high"
        )

    def test_calibrated_no_extreme_values(self, dem_calibrated_info):
        dem = dem_calibrated_info['dem']
        nodata = dem_calibrated_info['nodata']

        valid = dem.copy().astype(float)
        if nodata is not None:
            valid = valid[valid != nodata]
        valid = valid[~np.isnan(valid)]

        assert np.all(valid > -100), (
            f"Calibrated DEM has extreme low value: {valid.min():.1f}"
        )
        assert np.all(valid < 2000), (
            f"Calibrated DEM has extreme high value: {valid.max():.1f}"
        )


# ---------------------------------------------------------------------------
# 3. Nodata handling
# ---------------------------------------------------------------------------

class TestNodataHandling:
    def test_nodata_metadata_set(self, dem_calibrated_info):
        assert dem_calibrated_info['nodata'] is not None, (
            "Calibrated DEM must have nodata value set in metadata"
        )

    def test_raw_nodata_pixels_not_suitable(self, dem_raw_arr, suit_arr):
        """Pixels that had -9999 in the raw DEM must not be suitable."""
        nodata_mask = dem_raw_arr <= -9000
        num_nodata = int(np.sum(nodata_mask))
        assert num_nodata > 0, (
            "Expected nodata-contaminated pixels in raw DEM"
        )
        overlap = np.sum((nodata_mask) & (suit_arr == 1))
        assert overlap == 0, (
            f"{overlap} raw-nodata pixels marked suitable — "
            f"nodata was not properly detected/handled"
        )


# ---------------------------------------------------------------------------
# 4. Raster properties (dimensions, CRS, value ranges)
# ---------------------------------------------------------------------------

class TestRasterProperties:
    @pytest.mark.parametrize("raster", [
        'slope.tif', 'aspect.tif', 'tri.tif', 'suitability.tif',
    ])
    def test_dimensions_match_dem(self, raster, dem_calibrated_info):
        ds = gdal.Open(f'/app/output/{raster}')
        assert ds is not None, f"Cannot open /app/output/{raster}"
        assert ds.RasterXSize == dem_calibrated_info['nx'], (
            f"{raster} X size mismatch"
        )
        assert ds.RasterYSize == dem_calibrated_info['ny'], (
            f"{raster} Y size mismatch"
        )
        ds = None

    @pytest.mark.parametrize("raster", [
        'slope.tif', 'aspect.tif', 'tri.tif', 'suitability.tif',
    ])
    def test_crs_matches_dem(self, raster, dem_calibrated_info):
        dem_srs = osr.SpatialReference()
        dem_srs.ImportFromWkt(dem_calibrated_info['proj'])
        ds = gdal.Open(f'/app/output/{raster}')
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds.GetProjection())
        ds = None
        assert dem_srs.IsSame(out_srs), f"{raster} CRS differs from DEM"

    def test_slope_physical_range(self, slope_arr):
        ds = gdal.Open('/app/output/slope.tif')
        nodata = ds.GetRasterBand(1).GetNoDataValue()
        ds = None
        interior = slope_arr[2:-2, 2:-2]
        valid = interior[~np.isnan(interior)]
        if nodata is not None:
            valid = valid[valid != nodata]
        assert len(valid) > 0, "No valid slope pixels in interior"
        assert np.all(valid >= -0.01), "Slope has negative values"
        assert np.all(valid <= 90.01), "Slope exceeds 90 degrees"
        assert np.any(valid > 0.5), "No discernible slope in terrain"

    def test_aspect_physical_range(self, aspect_arr):
        ds = gdal.Open('/app/output/aspect.tif')
        nodata = ds.GetRasterBand(1).GetNoDataValue()
        ds = None
        interior = aspect_arr[2:-2, 2:-2]
        valid = interior[~np.isnan(interior)]
        if nodata is not None:
            valid = valid[valid != nodata]
        assert len(valid) > 0, "No valid aspect pixels in interior"
        assert np.all(valid >= -1.01), "Aspect has unexpected values"
        assert np.all(valid <= 360.01), "Aspect exceeds 360 degrees"

    def test_suitability_binary(self, suit_arr):
        unique = set(np.unique(suit_arr))
        assert unique.issubset({0, 1}), (
            f"Suitability not binary: {unique}"
        )


# ---------------------------------------------------------------------------
# 5. Slope spot-check via Horn's method on calibrated DEM
# ---------------------------------------------------------------------------

class TestSlopeSpotCheck:
    def test_slope_horns_method(self, dem_calibrated_info, slope_arr):
        dem = dem_calibrated_info['dem']
        nodata = dem_calibrated_info['nodata']
        px = dem_calibrated_info['gt'][1]

        # Pixels far from nodata and edges
        test_pixels = [(100, 100), (150, 150), (200, 200)]
        for r, c in test_pixels:
            # Verify 3x3 neighbourhood is all valid
            window = dem[r - 1:r + 2, c - 1:c + 2]
            if nodata is not None and np.any(window == nodata):
                continue
            if np.any(np.isnan(window)):
                continue

            dz_dx = (
                float(dem[r - 1, c + 1]) + 2 * float(dem[r, c + 1])
                + float(dem[r + 1, c + 1])
                - float(dem[r - 1, c - 1]) - 2 * float(dem[r, c - 1])
                - float(dem[r + 1, c - 1])
            ) / (8.0 * px)
            dz_dy = (
                float(dem[r + 1, c - 1]) + 2 * float(dem[r + 1, c])
                + float(dem[r + 1, c + 1])
                - float(dem[r - 1, c - 1]) - 2 * float(dem[r - 1, c])
                - float(dem[r - 1, c + 1])
            ) / (8.0 * px)
            expected = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))
            actual = float(slope_arr[r, c])
            assert abs(actual - expected) < 1.0, (
                f"Slope mismatch at ({r},{c}): got {actual:.3f}, "
                f"expected {expected:.3f}"
            )


# ---------------------------------------------------------------------------
# 6. Suitability criteria cross-check on calibrated DEM
# ---------------------------------------------------------------------------

class TestSuitabilityCriteria:
    def test_suitable_pixels_meet_criteria(
        self, spec, dem_calibrated_info, slope_arr, aspect_arr,
        tri_arr, suit_arr
    ):
        dem = dem_calibrated_info['dem']
        nodata = dem_calibrated_info['nodata']
        ny = dem_calibrated_info['ny']
        nx = dem_calibrated_info['nx']

        slope_min, slope_max = spec['slope_range_deg']
        aspect_min, aspect_max = spec['aspect_range_deg']
        elev_min, elev_max = spec['elevation_range_m']
        tri_max = spec['max_terrain_ruggedness_index']
        edge_buf = spec['edge_buffer_pixels']

        rows, cols = np.where(suit_arr == 1)
        assert len(rows) > 0, "No suitable pixels found at all"

        # Edge buffer
        assert np.all(rows >= edge_buf), "Suitable pixel in top edge buffer"
        assert np.all(rows < ny - edge_buf), (
            "Suitable pixel in bottom edge buffer"
        )
        assert np.all(cols >= edge_buf), "Suitable pixel in left edge buffer"
        assert np.all(cols < nx - edge_buf), (
            "Suitable pixel in right edge buffer"
        )

        # Slope bounds
        s = slope_arr[rows, cols]
        assert np.all(s >= slope_min - 0.5), (
            f"Suitable pixel slope {s.min():.3f} < min {slope_min}"
        )
        assert np.all(s <= slope_max + 0.5), (
            f"Suitable pixel slope {s.max():.3f} > max {slope_max}"
        )

        # Aspect bounds (excluding flat pixels)
        a = aspect_arr[rows, cols]
        assert np.all(a >= aspect_min - 0.5), (
            f"Suitable pixel aspect {a.min():.3f} < min {aspect_min}"
        )
        assert np.all(a <= aspect_max + 0.5), (
            f"Suitable pixel aspect {a.max():.3f} > max {aspect_max}"
        )

        # Elevation on calibrated DEM
        e = dem[rows, cols].astype(float)
        if nodata is not None:
            e = e[e != nodata]
        e = e[~np.isnan(e)]
        assert np.all(e >= elev_min - 0.5), (
            f"Suitable pixel elev {e.min():.3f} < min {elev_min}"
        )
        assert np.all(e <= elev_max + 0.5), (
            f"Suitable pixel elev {e.max():.3f} > max {elev_max}"
        )

        # TRI
        t = tri_arr[rows, cols]
        assert np.all(t <= tri_max + 0.5), (
            f"Suitable pixel TRI {t.max():.3f} > max {tri_max}"
        )


# ---------------------------------------------------------------------------
# 7. Exclusion zones — must be applied at correct geographic locations
# ---------------------------------------------------------------------------

class TestExclusionZones:
    def test_exclusion_buffer_respected(self, spec, dem_calibrated_info,
                                        suit_arr):
        gt = dem_calibrated_info['gt']
        pixel_size = gt[1]
        excl_buf_px = spec['exclusion_buffer_m'] / pixel_size

        # True UTM coordinates of the exclusion points
        # (the GeoJSON has swapped lat/lon — the agent must have detected
        # and corrected this; these are the ground-truth locations)
        exclusion_utm = [
            (503000.0, 4505000.0),
            (506000.0, 4502000.0),
            (501500.0, 4507000.0),
        ]

        suit_rows, suit_cols = np.where(suit_arr == 1)
        if len(suit_rows) == 0:
            pytest.skip("No suitable pixels to check")

        for e_utm, n_utm in exclusion_utm:
            col = (e_utm - gt[0]) / gt[1]
            row = (n_utm - gt[3]) / gt[5]

            if (0 <= col < dem_calibrated_info['nx']
                    and 0 <= row < dem_calibrated_info['ny']):
                dists = np.sqrt(
                    (suit_cols.astype(float) - col)**2
                    + (suit_rows.astype(float) - row)**2
                )
                min_dist = float(dists.min())
                assert min_dist >= excl_buf_px - 1.5, (
                    f"Suitable pixel at distance {min_dist:.1f} px from "
                    f"exclusion point ({e_utm}, {n_utm}), "
                    f"need {excl_buf_px:.1f} px"
                )


# ---------------------------------------------------------------------------
# 8. Connected component constraints
# ---------------------------------------------------------------------------

class TestContiguousRegions:
    def test_minimum_area(self, spec, suit_arr, dem_calibrated_info):
        pixel_area = dem_calibrated_info['gt'][1] ** 2
        min_pixels = spec['min_contiguous_area_m2'] / pixel_area

        conn = spec.get('connectivity', 8)
        if conn == 8:
            struct = ndimage.generate_binary_structure(2, 2)
        else:
            struct = ndimage.generate_binary_structure(2, 1)

        labeled, num = ndimage.label(suit_arr, structure=struct)
        for rid in range(1, num + 1):
            count = int(np.sum(labeled == rid))
            assert count >= min_pixels - 1, (
                f"Region {rid}: {count} pixels "
                f"({count * pixel_area:.0f} m2) < min "
                f"{spec['min_contiguous_area_m2']:.0f} m2"
            )

    def test_num_regions_matches_json(self, spec, results, suit_arr,
                                      dem_calibrated_info):
        pixel_area = dem_calibrated_info['gt'][1] ** 2
        min_pixels = spec['min_contiguous_area_m2'] / pixel_area

        conn = spec.get('connectivity', 8)
        if conn == 8:
            struct = ndimage.generate_binary_structure(2, 2)
        else:
            struct = ndimage.generate_binary_structure(2, 1)

        labeled, num = ndimage.label(suit_arr, structure=struct)
        valid_count = sum(
            1 for rid in range(1, num + 1)
            if np.sum(labeled == rid) >= min_pixels
        )
        assert results['num_suitable_regions'] == valid_count, (
            f"JSON reports {results['num_suitable_regions']} regions, "
            f"independent count is {valid_count}"
        )


# ---------------------------------------------------------------------------
# 9. results.json structure and consistency
# ---------------------------------------------------------------------------

class TestResultsJSON:
    def test_required_keys(self, results):
        for key in ['total_suitable_pixels', 'total_suitable_area_m2',
                     'num_suitable_regions', 'top_regions',
                     'optimal_region_id']:
            assert key in results, f"Missing key: {key}"

    def test_top_regions_fields(self, results):
        required = [
            'rank', 'region_id', 'pixel_count', 'area_m2',
            'centroid_utm_e', 'centroid_utm_n',
            'centroid_lon', 'centroid_lat',
            'mean_elevation', 'mean_slope', 'mean_aspect',
            'aspect_uniformity', 'score',
        ]
        assert len(results['top_regions']) > 0, "No top regions"
        for region in results['top_regions']:
            for field in required:
                assert field in region, (
                    f"Region {region.get('rank', '?')} missing: {field}"
                )

    def test_total_pixels_matches_raster(self, results, suit_arr):
        actual = int(np.sum(suit_arr == 1))
        assert results['total_suitable_pixels'] == actual, (
            f"JSON total_suitable_pixels={results['total_suitable_pixels']}, "
            f"raster count={actual}"
        )

    def test_area_consistent_with_pixels(self, results, dem_calibrated_info):
        pixel_area = dem_calibrated_info['gt'][1] ** 2
        expected = results['total_suitable_pixels'] * pixel_area
        assert abs(results['total_suitable_area_m2'] - expected) < 1.0

    def test_regions_sorted_by_score(self, results):
        scores = [r['score'] for r in results['top_regions']]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1] - 1e-9, (
                f"Regions not sorted: score[{i}]={scores[i]} < "
                f"score[{i + 1}]={scores[i + 1]}"
            )

    def test_optimal_region_is_rank1(self, results):
        assert results['optimal_region_id'] == (
            results['top_regions'][0]['region_id']
        )

    def test_ranks_sequential(self, results):
        ranks = [r['rank'] for r in results['top_regions']]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_top_n_size(self, results, spec):
        top_n = spec['scoring']['report_top_n']
        n_regions = results['num_suitable_regions']
        expected_len = min(top_n, n_regions)
        assert len(results['top_regions']) == expected_len


# ---------------------------------------------------------------------------
# 10. Region metric validity
# ---------------------------------------------------------------------------

class TestRegionMetrics:
    def test_aspect_uniformity_range(self, results):
        for r in results['top_regions']:
            assert 0.0 - 1e-6 <= r['aspect_uniformity'] <= 1.0 + 1e-6, (
                f"Region {r['region_id']} aspect_uniformity "
                f"{r['aspect_uniformity']} outside [0, 1]"
            )

    def test_elevation_within_spec_bounds(self, results, spec):
        lo, hi = spec['elevation_range_m']
        for r in results['top_regions']:
            assert lo - 0.5 <= r['mean_elevation'] <= hi + 0.5, (
                f"Region {r['region_id']} mean_elevation "
                f"{r['mean_elevation']} outside [{lo}, {hi}]"
            )

    def test_slope_within_spec_bounds(self, results, spec):
        lo, hi = spec['slope_range_deg']
        for r in results['top_regions']:
            assert lo - 0.5 <= r['mean_slope'] <= hi + 0.5, (
                f"Region {r['region_id']} mean_slope "
                f"{r['mean_slope']} outside [{lo}, {hi}]"
            )

    def test_pixel_count_area_consistency(self, results, dem_calibrated_info):
        pixel_area = dem_calibrated_info['gt'][1] ** 2
        for r in results['top_regions']:
            expected = r['pixel_count'] * pixel_area
            assert abs(r['area_m2'] - expected) < 1.0, (
                f"Region {r['region_id']} area {r['area_m2']} != "
                f"{r['pixel_count']} * {pixel_area}"
            )

    def test_centroids_within_dem_bounds(self, results, dem_calibrated_info):
        gt = dem_calibrated_info['gt']
        nx = dem_calibrated_info['nx']
        ny = dem_calibrated_info['ny']
        min_e = gt[0]
        max_e = gt[0] + nx * gt[1]
        min_n = gt[3] + ny * gt[5]
        max_n = gt[3]
        for r in results['top_regions']:
            assert min_e <= r['centroid_utm_e'] <= max_e, (
                f"Centroid E {r['centroid_utm_e']} outside DEM"
            )
            assert min_n <= r['centroid_utm_n'] <= max_n, (
                f"Centroid N {r['centroid_utm_n']} outside DEM"
            )

    def test_scores_in_valid_range(self, results, spec):
        w = spec['scoring']['weights']
        max_score = sum(v for v in w.values() if v > 0)
        min_score = sum(v for v in w.values() if v < 0)
        for r in results['top_regions']:
            assert min_score - 0.01 <= r['score'] <= max_score + 0.01, (
                f"Region {r['region_id']} score {r['score']} outside "
                f"[{min_score}, {max_score}]"
            )
