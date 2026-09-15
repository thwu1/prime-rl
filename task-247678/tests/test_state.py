
import json
import os

import numpy as np
import pytest
from osgeo import gdal, osr
from scipy import ndimage


class TestSuitabilityRasterStructure:
    """Verify the structural properties of the output suitability raster."""

    def test_suitability_tif_exists(self):
        assert os.path.exists('/app/output/suitability.tif'), \
            "Output raster /app/output/suitability.tif not found"

    def test_suitability_tif_opens_as_gdal(self):
        ds = gdal.Open('/app/output/suitability.tif')
        assert ds is not None, "Cannot open suitability.tif as a GDAL dataset"
        ds = None

    def test_single_band(self):
        ds = gdal.Open('/app/output/suitability.tif')
        assert ds.RasterCount == 1, \
            f"Expected 1 band, got {ds.RasterCount}"
        ds = None

    def test_dimensions(self):
        ds = gdal.Open('/app/output/suitability.tif')
        assert ds.RasterXSize == 80, \
            f"Expected 80 columns (4000m / 50m), got {ds.RasterXSize}"
        assert ds.RasterYSize == 80, \
            f"Expected 80 rows (4000m / 50m), got {ds.RasterYSize}"
        ds = None

    def test_crs_is_epsg32636(self):
        ds = gdal.Open('/app/output/suitability.tif')
        srs = osr.SpatialReference(ds.GetProjection())
        code = srs.GetAuthorityCode(None)
        assert code == '32636', \
            f"Expected EPSG:32636, got EPSG:{code}"
        ds = None

    def test_extent(self):
        ds = gdal.Open('/app/output/suitability.tif')
        gt = ds.GetGeoTransform()
        xmin = gt[0]
        ymax = gt[3]
        xmax = gt[0] + gt[1] * ds.RasterXSize
        ymin = gt[3] + gt[5] * ds.RasterYSize
        assert abs(xmin - 500000) < 1, f"xmin={xmin}, expected 500000"
        assert abs(ymin - 4000000) < 1, f"ymin={ymin}, expected 4000000"
        assert abs(xmax - 504000) < 1, f"xmax={xmax}, expected 504000"
        assert abs(ymax - 4004000) < 1, f"ymax={ymax}, expected 4004000"
        ds = None

    def test_pixel_size(self):
        ds = gdal.Open('/app/output/suitability.tif')
        gt = ds.GetGeoTransform()
        assert abs(gt[1] - 50.0) < 0.1, f"Pixel width={gt[1]}, expected 50"
        assert abs(gt[5] - (-50.0)) < 0.1, f"Pixel height={gt[5]}, expected -50"
        ds = None


class TestSuitabilityValues:
    """Verify the correctness of suitability pixel values."""

    @staticmethod
    def _load_raster():
        ds = gdal.Open('/app/output/suitability.tif')
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(float)
        gt = ds.GetGeoTransform()
        nodata = band.GetNoDataValue()
        if nodata is not None:
            valid_mask = data != nodata
        else:
            valid_mask = data != 0
        return data, gt, valid_mask

    def test_value_range(self):
        data, _, valid_mask = self._load_raster()
        valid = data[valid_mask]
        assert len(valid) > 0, "No valid pixels found"
        assert np.min(valid) >= 9.5, \
            f"Min suitability {np.min(valid):.1f} below expected minimum ~10"
        assert np.max(valid) <= 100.5, \
            f"Max suitability {np.max(valid):.1f} above expected maximum ~100"

    def test_pixel_at_road_intersection_outside_flood(self):
        """Pixel at col=40, row=60 (center 502025, 4000975):
        - On road intersection (proximity=0 -> high road score)
        - Far from hospitals (>500m -> high hospital score)
        - Outside both flood zones (-> high flood score)
        - Expected: maximum suitability = 100
        """
        data, _, _ = self._load_raster()
        val = data[60, 40]
        assert abs(val - 100.0) < 2.0, \
            f"Pixel at road intersection expected ~100, got {val:.1f}"

    def test_pixel_inside_flood_zone_1(self):
        """Pixel at col=5, row=75 (center 500275, 4000225):
        - Inside flood zone 1 (-> low flood score)
        - Far from hospitals (>500m -> high hospital score)
        - Far from roads (>300m -> low road score)
        - Expected: ~37
        """
        data, _, _ = self._load_raster()
        val = data[75, 5]
        assert abs(val - 37.0) < 5.0, \
            f"Pixel inside flood zone 1 expected ~37, got {val:.1f}"

    def test_pixel_inside_flood_zone_2(self):
        """Pixel at col=65, row=15 (center 503275, 4003225):
        - Inside flood zone 2 (-> low flood score)
        - Moderate hospital distance (~354m -> medium hospital score)
        - Moderate road distance (~250m -> medium road score)
        - Expected: ~30
        """
        data, _, _ = self._load_raster()
        val = data[15, 65]
        assert abs(val - 30.0) < 5.0, \
            f"Pixel inside flood zone 2 expected ~30, got {val:.1f}"

    def test_flood_zone_systematic_lower_suitability(self):
        """Flood zone pixels should have systematically lower mean than safe pixels."""
        data, _, _ = self._load_raster()
        fz1_mean = np.mean(data[50:80, 0:30])
        safe_mean = np.mean(data[30:50, 30:50])
        assert fz1_mean < safe_mean, \
            f"Flood zone 1 mean ({fz1_mean:.1f}) should be < safe zone mean ({safe_mean:.1f})"

    def test_flood_zone_2_lower_than_safe(self):
        """Flood zone 2 pixels should also have lower mean than safe pixels."""
        data, _, _ = self._load_raster()
        fz2_mean = np.mean(data[0:30, 50:80])
        safe_mean = np.mean(data[30:50, 30:50])
        assert fz2_mean < safe_mean, \
            f"Flood zone 2 mean ({fz2_mean:.1f}) should be < safe zone mean ({safe_mean:.1f})"


class TestCandidatesJson:
    """Verify the candidates.json output for contiguous patch analysis."""

    THRESHOLD = 70
    MIN_AREA_HA = 5.0
    PIXEL_AREA_HA = 0.25  # 50m * 50m = 2500 sq m = 0.25 ha

    @staticmethod
    def _load_candidates():
        with open('/app/output/candidates.json') as f:
            return json.load(f)

    @staticmethod
    def _load_raster():
        ds = gdal.Open('/app/output/suitability.tif')
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(float)
        gt = ds.GetGeoTransform()
        nodata = band.GetNoDataValue()
        if nodata is not None:
            valid_mask = data != nodata
        else:
            valid_mask = data != 0
        return data, gt, valid_mask

    def test_candidates_file_exists(self):
        assert os.path.exists('/app/output/candidates.json'), \
            "Output file /app/output/candidates.json not found"

    def test_candidates_is_list(self):
        candidates = self._load_candidates()
        assert isinstance(candidates, list), \
            f"candidates.json should be a JSON array, got {type(candidates).__name__}"

    def test_candidates_have_required_fields(self):
        candidates = self._load_candidates()
        required = ['patch_id', 'centroid_x', 'centroid_y',
                     'area_ha', 'mean_suitability', 'max_suitability']
        for i, c in enumerate(candidates):
            for field in required:
                assert field in c, \
                    f"Candidate {i} missing required field '{field}'"

    def test_candidates_min_area(self):
        """Every candidate patch must meet the minimum area threshold."""
        candidates = self._load_candidates()
        for c in candidates:
            assert c['area_ha'] >= self.MIN_AREA_HA - 0.01, \
                f"Patch {c['patch_id']} area {c['area_ha']} ha < min {self.MIN_AREA_HA} ha"

    def test_candidates_sorted_by_mean_suitability(self):
        """Candidates must be sorted by mean_suitability descending."""
        candidates = self._load_candidates()
        if len(candidates) < 2:
            return
        for i in range(len(candidates) - 1):
            assert candidates[i]['mean_suitability'] >= candidates[i + 1]['mean_suitability'], \
                f"Candidates not sorted: patch {candidates[i]['patch_id']} " \
                f"({candidates[i]['mean_suitability']}) < " \
                f"patch {candidates[i+1]['patch_id']} ({candidates[i+1]['mean_suitability']})"

    def test_candidates_centroids_within_extent(self):
        """All candidate centroids must be within the study area."""
        candidates = self._load_candidates()
        for c in candidates:
            assert 500000 <= c['centroid_x'] <= 504000, \
                f"Patch {c['patch_id']} centroid_x={c['centroid_x']} outside extent"
            assert 4000000 <= c['centroid_y'] <= 4004000, \
                f"Patch {c['patch_id']} centroid_y={c['centroid_y']} outside extent"

    def test_candidates_not_in_flood_zones(self):
        """No candidate centroid should fall inside a flood zone."""
        candidates = self._load_candidates()
        for c in candidates:
            x, y = c['centroid_x'], c['centroid_y']
            in_fz1 = (500000 <= x <= 501500) and (4000000 <= y <= 4001500)
            in_fz2 = (502500 <= x <= 504000) and (4002500 <= y <= 4004000)
            assert not (in_fz1 or in_fz2), \
                f"Patch {c['patch_id']} centroid ({x:.0f},{y:.0f}) is inside a flood zone"

    def test_candidates_max_above_threshold(self):
        """Every candidate must have max_suitability > threshold."""
        candidates = self._load_candidates()
        for c in candidates:
            assert c['max_suitability'] > self.THRESHOLD, \
                f"Patch {c['patch_id']} max_suitability {c['max_suitability']} <= threshold {self.THRESHOLD}"

    def test_candidates_count_matches_independent_analysis(self):
        """Independently compute connected components and verify candidate count."""
        data, gt, valid_mask = self._load_raster()
        above_mask = (data > self.THRESHOLD) & valid_mask
        # 4-connectivity structure
        structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
        labels, num_features = ndimage.label(above_mask, structure=structure)

        pixel_area_ha = abs(gt[1] * gt[5]) / 10000.0
        qualifying = 0
        for label_id in range(1, num_features + 1):
            area_ha = np.sum(labels == label_id) * pixel_area_ha
            if area_ha >= self.MIN_AREA_HA:
                qualifying += 1

        candidates = self._load_candidates()
        assert len(candidates) == qualifying, \
            f"Expected {qualifying} qualifying patches (4-connectivity), got {len(candidates)}"

    def test_candidates_total_area_consistent(self):
        """Sum of candidate areas should not exceed total suitable area."""
        data, gt, valid_mask = self._load_raster()
        above_mask = (data > self.THRESHOLD) & valid_mask
        pixel_area_ha = abs(gt[1] * gt[5]) / 10000.0
        total_suitable_ha = np.sum(above_mask) * pixel_area_ha

        candidates = self._load_candidates()
        candidates_area = sum(c['area_ha'] for c in candidates)
        assert candidates_area <= total_suitable_ha + 0.1, \
            f"Candidates total area {candidates_area:.2f} ha > total suitable {total_suitable_ha:.2f} ha"

    def test_candidate_mean_suitability_verified(self):
        """Verify the best candidate's mean suitability against the raster."""
        data, gt, valid_mask = self._load_raster()
        above_mask = (data > self.THRESHOLD) & valid_mask
        structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
        labels, num_features = ndimage.label(above_mask, structure=structure)

        candidates = self._load_candidates()
        if not candidates:
            pytest.skip("No candidates to verify")

        best = candidates[0]
        pixel_area_ha = abs(gt[1] * gt[5]) / 10000.0

        # Find the label that matches the best candidate by area and mean
        found_match = False
        for label_id in range(1, num_features + 1):
            mask = labels == label_id
            area_ha = np.sum(mask) * pixel_area_ha
            if area_ha < self.MIN_AREA_HA:
                continue
            mean_suit = float(np.mean(data[mask]))
            if abs(mean_suit - best['mean_suitability']) < 1.0:
                found_match = True
                break

        assert found_match, \
            f"Could not find a matching patch for best candidate " \
            f"(mean_suitability={best['mean_suitability']})"


class TestResultsJson:
    """Verify the results.json output file."""

    THRESHOLD = 70
    MIN_AREA_HA = 5.0

    @staticmethod
    def _load_results():
        with open('/app/output/results.json') as f:
            return json.load(f)

    @staticmethod
    def _load_candidates():
        with open('/app/output/candidates.json') as f:
            return json.load(f)

    @staticmethod
    def _load_raster():
        ds = gdal.Open('/app/output/suitability.tif')
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(float)
        gt = ds.GetGeoTransform()
        nodata = band.GetNoDataValue()
        if nodata is not None:
            valid_mask = data != nodata
        else:
            valid_mask = data != 0
        return data, gt, valid_mask

    def test_results_json_exists(self):
        assert os.path.exists('/app/output/results.json'), \
            "Output file /app/output/results.json not found"

    def test_required_fields_present(self):
        results = self._load_results()
        required_top = ['total_suitable_area_ha', 'num_candidate_patches',
                        'best_candidate', 'mean_suitability_all']
        for key in required_top:
            assert key in results, f"Missing required key '{key}' in results.json"

        if results['best_candidate'] is not None:
            bc_required = ['patch_id', 'centroid_x', 'centroid_y',
                           'area_ha', 'mean_suitability']
            for key in bc_required:
                assert key in results['best_candidate'], \
                    f"Missing key '{key}' in best_candidate"

    def test_total_suitable_area_matches_raster(self):
        """total_suitable_area_ha must match pixel count above threshold."""
        results = self._load_results()
        data, gt, valid_mask = self._load_raster()
        above_mask = (data > self.THRESHOLD) & valid_mask
        pixel_area_ha = abs(gt[1] * gt[5]) / 10000.0
        expected = round(np.sum(above_mask) * pixel_area_ha, 2)
        assert abs(results['total_suitable_area_ha'] - expected) < 1.0, \
            f"total_suitable_area_ha: got {results['total_suitable_area_ha']}, expected {expected}"

    def test_num_candidate_patches_matches_candidates_json(self):
        """num_candidate_patches must equal length of candidates.json."""
        results = self._load_results()
        candidates = self._load_candidates()
        assert results['num_candidate_patches'] == len(candidates), \
            f"num_candidate_patches={results['num_candidate_patches']} " \
            f"!= len(candidates.json)={len(candidates)}"

    def test_best_candidate_matches_first_candidate(self):
        """best_candidate in results.json must match first entry in candidates.json."""
        results = self._load_results()
        candidates = self._load_candidates()
        if not candidates:
            assert results['best_candidate'] is None, \
                "best_candidate should be None when no candidates exist"
            return

        best = results['best_candidate']
        first = candidates[0]
        assert best['patch_id'] == first['patch_id'], \
            f"best_candidate patch_id {best['patch_id']} != first candidate {first['patch_id']}"
        assert abs(best['mean_suitability'] - first['mean_suitability']) < 0.1, \
            f"best_candidate mean_suitability mismatch"
        assert abs(best['area_ha'] - first['area_ha']) < 0.1, \
            f"best_candidate area_ha mismatch"

    def test_mean_suitability_all_matches_raster(self):
        """mean_suitability_all must match the raster's actual mean."""
        results = self._load_results()
        data, _, valid_mask = self._load_raster()
        valid = data[valid_mask]
        expected_mean = round(float(np.mean(valid)), 2)
        assert abs(results['mean_suitability_all'] - expected_mean) < 2.0, \
            f"mean_suitability_all: got {results['mean_suitability_all']}, expected {expected_mean}"

    def test_best_candidate_centroid_within_extent(self):
        """Best candidate centroid must be within the study area."""
        results = self._load_results()
        if results['best_candidate'] is None:
            pytest.skip("No best candidate")
        bc = results['best_candidate']
        assert 500000 <= bc['centroid_x'] <= 504000, \
            f"best_candidate centroid_x={bc['centroid_x']} outside extent"
        assert 4000000 <= bc['centroid_y'] <= 4004000, \
            f"best_candidate centroid_y={bc['centroid_y']} outside extent"

    def test_best_candidate_not_in_flood_zone(self):
        """Best candidate centroid must not be in a flood zone."""
        results = self._load_results()
        if results['best_candidate'] is None:
            pytest.skip("No best candidate")
        x = results['best_candidate']['centroid_x']
        y = results['best_candidate']['centroid_y']
        in_fz1 = (500000 <= x <= 501500) and (4000000 <= y <= 4001500)
        in_fz2 = (502500 <= x <= 504000) and (4002500 <= y <= 4004000)
        assert not (in_fz1 or in_fz2), \
            f"Best candidate centroid ({x:.0f},{y:.0f}) is inside a flood zone"
