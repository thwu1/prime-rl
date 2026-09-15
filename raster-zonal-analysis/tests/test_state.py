#!/usr/bin/env python3
"""Tests for geospatial spectral band identification and analysis."""

import pytest
import csv
import json
import os
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from pyproj import Transformer
from shapely.geometry import Point, Polygon, MultiPolygon, box as shapely_box
from shapely import make_valid
from scipy.ndimage import map_coordinates

# Ground truth: band 0=NIR, 1=Blue, 2=Red, 3=Green
CORRECT_MAPPING = {"red": 2, "green": 3, "blue": 1, "nir": 0}


@pytest.fixture(scope="module")
def raster_data():
    """Load raster and compute indices with correct band mapping."""
    with rasterio.open('/app/data/imagery.tif') as src:
        data = src.read()
        transform = src.transform
        H, W = src.height, src.width

    nir = data[CORRECT_MAPPING["nir"]].astype(np.float64)
    red = data[CORRECT_MAPPING["red"]].astype(np.float64)
    green = data[CORRECT_MAPPING["green"]].astype(np.float64)

    nan_mask = np.zeros((H, W), dtype=bool)
    for b in range(4):
        nan_mask |= np.isnan(data[b])

    with np.errstate(invalid='ignore', divide='ignore'):
        ndvi = (nir - red) / (nir + red)
        ndwi = (green - nir) / (green + nir)
    ndvi[nan_mask] = np.nan
    ndwi[nan_mask] = np.nan

    return {
        'data': data, 'transform': transform,
        'ndvi': ndvi, 'ndwi': ndwi,
        'nan_mask': nan_mask, 'H': H, 'W': W,
    }


@pytest.fixture(scope="module")
def zones_utm():
    """Load zones, reproject to UTM, repair invalid geometries."""
    with open('/app/data/zones.geojson') as f:
        gj = json.load(f)
    t = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
    result = []
    for feat in gj['features']:
        zid = feat['properties']['zone_id']
        coords = feat['geometry']['coordinates'][0]
        utm_coords = [t.transform(lon, lat) for lon, lat in coords]
        geom = Polygon(utm_coords)
        if not geom.is_valid:
            geom = make_valid(geom)
        result.append({'zone_id': zid, 'geom': geom})
    result.sort(key=lambda z: z['zone_id'])
    return result


@pytest.fixture(scope="module")
def stations():
    """Load station points from CSV (UTM coordinates)."""
    result = []
    with open('/app/data/samples.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            result.append({
                'station_id': int(row['id']),
                'x': float(row['x']),
                'y': float(row['y']),
            })
    result.sort(key=lambda s: s['station_id'])
    return result


def compute_expected_zonal_stats(raster_data, zones_utm):
    """Recompute expected zonal statistics with NaN handling."""
    H, W = raster_data['H'], raster_data['W']
    transform = raster_data['transform']
    ndvi = raster_data['ndvi']
    ndwi = raster_data['ndwi']
    nan_mask = raster_data['nan_mask']

    ox, oy = transform.c, transform.f
    px, py = transform.a, -transform.e
    raster_box = shapely_box(ox, oy - H * py, ox + W * px, oy)

    results = []
    for zone in zones_utm:
        zid = zone['zone_id']
        geom = zone['geom']
        clipped = geom.intersection(raster_box)
        if clipped.is_empty:
            continue

        mask = geometry_mask([clipped], out_shape=(H, W),
                             transform=transform, invert=True)
        valid_mask = mask & ~nan_mask
        ndvi_vals = ndvi[valid_mask]
        ndwi_vals = ndwi[valid_mask]

        results.append({
            'zone_id': zid,
            'ndvi_mean': float(np.mean(ndvi_vals)),
            'ndvi_std': float(np.std(ndvi_vals)),
            'ndvi_median': float(np.median(ndvi_vals)),
            'ndwi_mean': float(np.mean(ndwi_vals)),
            'ndwi_std': float(np.std(ndwi_vals)),
            'ndwi_median': float(np.median(ndwi_vals)),
            'valid_pixels': int(np.sum(valid_mask)),
        })
    results.sort(key=lambda r: r['zone_id'])
    return results


def compute_expected_station_values(raster_data, stations, zones_utm):
    """Recompute expected station values with correct band mapping."""
    data = raster_data['data']
    transform = raster_data['transform']
    ox, oy = transform.c, transform.f
    px, py = transform.a, -transform.e

    nir_idx = CORRECT_MAPPING['nir']
    red_idx = CORRECT_MAPPING['red']
    green_idx = CORRECT_MAPPING['green']

    results = []
    for st in stations:
        sid = st['station_id']
        x, y = st['x'], st['y']

        col = (x - ox) / px - 0.5
        row = (oy - y) / py - 0.5

        nir_val = float(map_coordinates(data[nir_idx].astype(np.float64),
                                        [[row], [col]], order=1, mode='nearest')[0])
        red_val = float(map_coordinates(data[red_idx].astype(np.float64),
                                        [[row], [col]], order=1, mode='nearest')[0])
        green_val = float(map_coordinates(data[green_idx].astype(np.float64),
                                          [[row], [col]], order=1, mode='nearest')[0])

        ndvi_i = (nir_val - red_val) / (nir_val + red_val)
        ndwi_i = (green_val - nir_val) / (green_val + nir_val)

        pt = Point(x, y)
        zone_id = None
        for zone in zones_utm:
            if zone['geom'].contains(pt):
                zone_id = zone['zone_id']
                break

        results.append({
            'station_id': sid, 'zone_id': zone_id,
            'ndvi': ndvi_i, 'ndwi': ndwi_i,
        })
    results.sort(key=lambda r: r['station_id'])
    return results


# ---- File existence ----

class TestOutputFiles:
    def test_band_mapping_exists(self):
        assert os.path.exists('/app/output/band_mapping.json'), \
            "Missing /app/output/band_mapping.json"

    def test_zonal_stats_exists(self):
        assert os.path.exists('/app/output/zonal_stats.csv'), \
            "Missing /app/output/zonal_stats.csv"

    def test_station_values_exists(self):
        assert os.path.exists('/app/output/station_values.csv'), \
            "Missing /app/output/station_values.csv"

    def test_correlation_exists(self):
        assert os.path.exists('/app/output/correlation.json'), \
            "Missing /app/output/correlation.json"


# ---- Band mapping ----

class TestBandMapping:
    def test_all_bands_assigned(self):
        with open('/app/output/band_mapping.json') as f:
            mapping = json.load(f)
        assert set(mapping.keys()) == {'red', 'green', 'blue', 'nir'}, \
            f"Expected keys red/green/blue/nir, got {list(mapping.keys())}"
        assert set(mapping.values()) == {0, 1, 2, 3}, \
            f"Band indices must be 0-3, got {list(mapping.values())}"

    def test_nir_identification(self):
        """NIR has highest mean reflectance in a vegetation-dominated scene."""
        with open('/app/output/band_mapping.json') as f:
            mapping = json.load(f)
        assert mapping['nir'] == CORRECT_MAPPING['nir'], \
            f"NIR band incorrect: got {mapping['nir']}, expected {CORRECT_MAPPING['nir']}"

    def test_blue_identification(self):
        """Blue has lowest mean reflectance due to chlorophyll absorption + scattering."""
        with open('/app/output/band_mapping.json') as f:
            mapping = json.load(f)
        assert mapping['blue'] == CORRECT_MAPPING['blue'], \
            f"Blue band incorrect: got {mapping['blue']}, expected {CORRECT_MAPPING['blue']}"

    def test_red_identification(self):
        """Red has second-lowest mean (vegetation absorbs red strongly)."""
        with open('/app/output/band_mapping.json') as f:
            mapping = json.load(f)
        assert mapping['red'] == CORRECT_MAPPING['red'], \
            f"Red band incorrect: got {mapping['red']}, expected {CORRECT_MAPPING['red']}"

    def test_green_identification(self):
        """Green has second-highest mean (green peak in vegetation reflectance)."""
        with open('/app/output/band_mapping.json') as f:
            mapping = json.load(f)
        assert mapping['green'] == CORRECT_MAPPING['green'], \
            f"Green band incorrect: got {mapping['green']}, expected {CORRECT_MAPPING['green']}"


# ---- Zonal statistics ----

class TestZonalStats:
    def test_correct_columns(self):
        with open('/app/output/zonal_stats.csv') as f:
            reader = csv.DictReader(f)
            expected = {'zone_id', 'ndvi_mean', 'ndvi_std', 'ndvi_median',
                        'ndwi_mean', 'ndwi_std', 'ndwi_median', 'valid_pixels'}
            assert set(reader.fieldnames) == expected, \
                f"Column mismatch: got {reader.fieldnames}"

    def test_six_zones(self):
        with open('/app/output/zonal_stats.csv') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 6, f"Expected 6 zones, got {len(rows)}"

    def test_zone_ids_complete(self):
        with open('/app/output/zonal_stats.csv') as f:
            ids = sorted(int(r['zone_id']) for r in csv.DictReader(f))
        assert ids == [1, 2, 3, 4, 5, 6]

    def test_ndvi_in_valid_range(self):
        with open('/app/output/zonal_stats.csv') as f:
            for row in csv.DictReader(f):
                mean = float(row['ndvi_mean'])
                assert -1.0 <= mean <= 1.0, \
                    f"Zone {row['zone_id']}: NDVI mean {mean} out of range"

    def test_zone2_nan_handling(self, raster_data, zones_utm):
        """Zone 2 overlaps NaN-corrupted scan lines; valid_pixels must be reduced."""
        expected = compute_expected_zonal_stats(raster_data, zones_utm)
        z2_exp = [z for z in expected if z['zone_id'] == 2][0]

        with open('/app/output/zonal_stats.csv') as f:
            rows = {int(r['zone_id']): r for r in csv.DictReader(f)}

        z2_actual = int(rows[2]['valid_pixels'])
        assert abs(z2_actual - z2_exp['valid_pixels']) <= 15, \
            f"Zone 2 valid_pixels: got {z2_actual}, expected ~{z2_exp['valid_pixels']}"

    def test_zone3_geometry_repair(self, raster_data, zones_utm):
        """Zone 3 self-intersecting bowtie: repaired area ~half of bounding rect."""
        expected = compute_expected_zonal_stats(raster_data, zones_utm)
        z3_exp = [z for z in expected if z['zone_id'] == 3][0]

        with open('/app/output/zonal_stats.csv') as f:
            rows = {int(r['zone_id']): r for r in csv.DictReader(f)}

        z3_actual = int(rows[3]['valid_pixels'])
        assert z3_actual < 3000, \
            f"Zone 3 valid_pixels={z3_actual} too high (bowtie repair expected)"
        assert z3_actual > 500, \
            f"Zone 3 valid_pixels={z3_actual} too low"
        assert abs(z3_actual - z3_exp['valid_pixels']) <= 15, \
            f"Zone 3 valid_pixels: got {z3_actual}, expected ~{z3_exp['valid_pixels']}"

    def test_zone4_partial_extent(self):
        """Zone 4 extends outside raster boundary."""
        with open('/app/output/zonal_stats.csv') as f:
            rows = {int(r['zone_id']): r for r in csv.DictReader(f)}
        z4_count = int(rows[4]['valid_pixels'])
        assert 500 < z4_count < 3000, \
            f"Zone 4 valid_pixels={z4_count} outside expected range for partial overlap"

    def test_zonal_stats_values(self, raster_data, zones_utm):
        expected = compute_expected_zonal_stats(raster_data, zones_utm)
        with open('/app/output/zonal_stats.csv') as f:
            actual = sorted(csv.DictReader(f), key=lambda r: int(r['zone_id']))

        for exp, act in zip(expected, actual):
            zid = exp['zone_id']
            assert int(act['zone_id']) == zid

            act_vp = int(act['valid_pixels'])
            assert abs(act_vp - exp['valid_pixels']) <= 15, \
                f"Zone {zid}: valid_pixels {act_vp} vs expected {exp['valid_pixels']}"

            for key in ['ndvi_mean', 'ndvi_std', 'ndvi_median',
                        'ndwi_mean', 'ndwi_std', 'ndwi_median']:
                a = float(act[key])
                e = exp[key]
                assert abs(a - e) < 0.03, \
                    f"Zone {zid}: {key} actual={a:.6f} expected={e:.6f}"


# ---- Station values ----

class TestStationValues:
    def test_correct_columns(self):
        with open('/app/output/station_values.csv') as f:
            reader = csv.DictReader(f)
            expected = {'station_id', 'zone_id', 'ndvi', 'ndwi'}
            assert set(reader.fieldnames) == expected

    def test_fifteen_stations(self):
        with open('/app/output/station_values.csv') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 15, f"Expected 15 stations, got {len(rows)}"

    def test_zone_assignments(self, raster_data, stations, zones_utm):
        expected = compute_expected_station_values(raster_data, stations, zones_utm)
        with open('/app/output/station_values.csv') as f:
            actual = sorted(csv.DictReader(f), key=lambda r: int(r['station_id']))

        for exp, act in zip(expected, actual):
            sid = exp['station_id']
            assert int(act['station_id']) == sid
            assert int(act['zone_id']) == exp['zone_id'], \
                f"Station {sid}: zone {act['zone_id']} vs expected {exp['zone_id']}"

    def test_spectral_indices(self, raster_data, stations, zones_utm):
        expected = compute_expected_station_values(raster_data, stations, zones_utm)
        with open('/app/output/station_values.csv') as f:
            actual = sorted(csv.DictReader(f), key=lambda r: int(r['station_id']))

        for exp, act in zip(expected, actual):
            sid = exp['station_id']
            for key in ['ndvi', 'ndwi']:
                a = float(act[key])
                e = exp[key]
                assert abs(a - e) < 0.03, \
                    f"Station {sid}: {key} actual={a:.6f} expected={e:.6f}"

    def test_bilinear_not_nearest(self, raster_data, stations):
        """Verify bilinear interpolation was used (not nearest-neighbor)."""
        data = raster_data['data']
        transform = raster_data['transform']
        ox, oy = transform.c, transform.f
        px_size, py_size = transform.a, -transform.e
        nir_idx = CORRECT_MAPPING['nir']
        red_idx = CORRECT_MAPPING['red']

        with open('/app/output/station_values.csv') as f:
            actual = sorted(csv.DictReader(f), key=lambda r: int(r['station_id']))

        mismatches = 0
        for st, act_row in zip(stations, actual):
            col_frac = (st['x'] - ox) / px_size
            row_frac = (oy - st['y']) / py_size
            nc = min(max(int(round(col_frac - 0.5)), 0), data.shape[2] - 1)
            nr = min(max(int(round(row_frac - 0.5)), 0), data.shape[1] - 1)

            nn_nir = float(data[nir_idx, nr, nc])
            nn_red = float(data[red_idx, nr, nc])
            if (nn_nir + nn_red) != 0:
                nn_ndvi = (nn_nir - nn_red) / (nn_nir + nn_red)
            else:
                nn_ndvi = 0.0

            actual_ndvi = float(act_row['ndvi'])
            if abs(actual_ndvi - nn_ndvi) > 0.001:
                mismatches += 1

        assert mismatches >= 5, \
            ("Bilinear interpolation expected: most station values should "
             f"differ from nearest-neighbor, but only {mismatches}/15 differed")

    def test_zone3_stations_assigned(self, raster_data, stations, zones_utm):
        """Stations inside repaired Zone 3 bowtie must be correctly assigned."""
        expected = compute_expected_station_values(raster_data, stations, zones_utm)
        with open('/app/output/station_values.csv') as f:
            actual = {int(r['station_id']): r for r in csv.DictReader(f)}

        for exp in expected:
            if exp['zone_id'] == 3:
                sid = exp['station_id']
                assert int(actual[sid]['zone_id']) == 3, \
                    f"Station {sid} should be in zone 3 (repaired bowtie geometry)"


# ---- Correlation ----

class TestCorrelation:
    def test_keys(self):
        with open('/app/output/correlation.json') as f:
            data = json.load(f)
        assert 'ndvi_pearson_r' in data
        assert 'ndwi_pearson_r' in data

    def test_range(self):
        with open('/app/output/correlation.json') as f:
            data = json.load(f)
        for key in ['ndvi_pearson_r', 'ndwi_pearson_r']:
            assert -1.0 <= data[key] <= 1.0, f"{key}={data[key]} outside [-1, 1]"

    def test_correlation_values(self, raster_data, zones_utm, stations):
        zonal = compute_expected_zonal_stats(raster_data, zones_utm)
        station_vals = compute_expected_station_values(raster_data, stations, zones_utm)

        zone_ndvi = {z['zone_id']: z['ndvi_mean'] for z in zonal}
        zone_ndwi = {z['zone_id']: z['ndwi_mean'] for z in zonal}

        st_ndvi, zm_ndvi, st_ndwi, zm_ndwi = [], [], [], []
        for sv in station_vals:
            zid = sv['zone_id']
            if zid in zone_ndvi:
                st_ndvi.append(sv['ndvi'])
                zm_ndvi.append(zone_ndvi[zid])
                st_ndwi.append(sv['ndwi'])
                zm_ndwi.append(zone_ndwi[zid])

        exp_ndvi_r = float(np.corrcoef(st_ndvi, zm_ndvi)[0, 1])
        exp_ndwi_r = float(np.corrcoef(st_ndwi, zm_ndwi)[0, 1])

        with open('/app/output/correlation.json') as f:
            actual = json.load(f)

        assert abs(actual['ndvi_pearson_r'] - exp_ndvi_r) < 0.08, \
            f"NDVI r: {actual['ndvi_pearson_r']:.6f} vs expected {exp_ndvi_r:.6f}"
        assert abs(actual['ndwi_pearson_r'] - exp_ndwi_r) < 0.08, \
            f"NDWI r: {actual['ndwi_pearson_r']:.6f} vs expected {exp_ndwi_r:.6f}"
