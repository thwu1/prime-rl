
import pytest
import csv
import json
import os
from shapely.geometry import shape, Point
from shapely.ops import transform as shapely_transform
from pyproj import Transformer

DATA_DIR = '/app/data'
RESULTS_DIR = '/app/results'

# ============================================================
# Helpers
# ============================================================

t_32633_to_4326 = Transformer.from_crs("EPSG:32633", "EPSG:4326", always_xy=True)
t_3035_to_4326 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
t_4326_to_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
t_32633_to_3035 = Transformer.from_crs("EPSG:32633", "EPSG:3035", always_xy=True)


def xform(geom, transformer):
    """Transform a shapely geometry using a pyproj Transformer."""
    return shapely_transform(transformer.transform, geom)


def load_stations():
    stations = []
    with open(os.path.join(DATA_DIR, 'stations.csv')) as f:
        for row in csv.DictReader(f):
            stations.append({
                'id': int(row['id']),
                'longitude': float(row['longitude']),
                'latitude': float(row['latitude']),
                'elevation_m': float(row['elevation_m']),
                'pollutant_reading': float(row['pollutant_reading']),
                'point_4326': Point(float(row['longitude']), float(row['latitude']))
            })
    return stations


def load_geojson(filename):
    with open(os.path.join(DATA_DIR, filename)) as f:
        return json.load(f)


def load_result_csv(filename):
    with open(os.path.join(RESULTS_DIR, filename)) as f:
        return list(csv.DictReader(f))


# ============================================================
# Analysis 1: District statistics
# ============================================================

class TestAnalysis1:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'analysis_1.csv'))

    def test_columns(self):
        rows = load_result_csv('analysis_1.csv')
        assert len(rows) > 0
        expected = {'district_id', 'num_stations', 'avg_pollutant', 'max_pollutant', 'area_km2'}
        assert expected == set(rows[0].keys())

    def test_row_count(self):
        rows = load_result_csv('analysis_1.csv')
        assert len(rows) == 12

    def test_all_districts_present(self):
        rows = load_result_csv('analysis_1.csv')
        ids = {r['district_id'] for r in rows}
        assert ids == {f'D{i:02d}' for i in range(1, 13)}

    def test_station_counts_match_independent(self):
        """Cross-validate station-to-district assignment using Python."""
        stations = load_stations()
        districts_gj = load_geojson('districts.geojson')

        # Build district polygons in EPSG:4326
        district_polys = []
        for feat in districts_gj['features']:
            geom_32633 = shape(feat['geometry'])
            geom_4326 = xform(geom_32633, t_32633_to_4326)
            district_polys.append({
                'district_id': feat['properties']['district_id'],
                'geom': geom_4326
            })

        expected_counts = {}
        for d in district_polys:
            expected_counts[d['district_id']] = sum(
                1 for s in stations if d['geom'].contains(s['point_4326'])
            )

        rows = load_result_csv('analysis_1.csv')
        for row in rows:
            did = row['district_id']
            assert int(row['num_stations']) == expected_counts[did], \
                f"District {did}: expected {expected_counts[did]}, got {row['num_stations']}"

    def test_pollutant_averages(self):
        """Cross-validate average and max pollutant per district."""
        stations = load_stations()
        districts_gj = load_geojson('districts.geojson')

        district_polys = []
        for feat in districts_gj['features']:
            geom_32633 = shape(feat['geometry'])
            geom_4326 = xform(geom_32633, t_32633_to_4326)
            district_polys.append({
                'district_id': feat['properties']['district_id'],
                'geom': geom_4326
            })

        expected = {}
        for d in district_polys:
            readings = [s['pollutant_reading'] for s in stations
                        if d['geom'].contains(s['point_4326'])]
            if readings:
                expected[d['district_id']] = {
                    'avg': round(sum(readings) / len(readings), 2),
                    'max': round(max(readings), 2)
                }

        rows = load_result_csv('analysis_1.csv')
        for row in rows:
            did = row['district_id']
            if did in expected:
                assert abs(float(row['avg_pollutant']) - expected[did]['avg']) < 0.1, \
                    f"District {did}: avg_pollutant mismatch"
                assert abs(float(row['max_pollutant']) - expected[did]['max']) < 0.1, \
                    f"District {did}: max_pollutant mismatch"

    def test_area_reasonable(self):
        """Each district is ~2deg lon x 1.25deg lat -> ~15,000-25,000 km2."""
        rows = load_result_csv('analysis_1.csv')
        for row in rows:
            area = float(row['area_km2'])
            assert 5000 < area < 40000, \
                f"District {row['district_id']}: area {area} km2 unreasonable"

    def test_area_independent(self):
        """Cross-validate area using shapely + pyproj."""
        districts_gj = load_geojson('districts.geojson')

        rows = load_result_csv('analysis_1.csv')
        result_areas = {r['district_id']: float(r['area_km2']) for r in rows}

        for feat in districts_gj['features']:
            did = feat['properties']['district_id']
            geom_32633 = shape(feat['geometry'])
            geom_3035 = xform(geom_32633, t_32633_to_3035)
            expected_area_km2 = geom_3035.area / 1e6
            assert abs(result_areas[did] - expected_area_km2) / expected_area_km2 < 0.01, \
                f"District {did}: area mismatch ({result_areas[did]} vs {expected_area_km2:.2f})"


# ============================================================
# Analysis 2: DBSCAN clustering
# ============================================================

class TestAnalysis2:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'analysis_2.csv'))

    def test_columns(self):
        rows = load_result_csv('analysis_2.csv')
        assert len(rows) > 0
        assert set(rows[0].keys()) == {'station_id', 'cluster_id', 'cluster_size'}

    def test_row_count(self):
        rows = load_result_csv('analysis_2.csv')
        assert len(rows) == 200

    def test_all_stations_present(self):
        rows = load_result_csv('analysis_2.csv')
        ids = {int(r['station_id']) for r in rows}
        assert ids == set(range(1, 201))

    def test_cluster_consistency(self):
        """cluster_size must match the actual count per cluster_id."""
        rows = load_result_csv('analysis_2.csv')
        clusters = {}
        for row in rows:
            cid = int(row['cluster_id'])
            clusters.setdefault(cid, []).append(row)

        for cid, members in clusters.items():
            if cid == -1:
                for m in members:
                    assert int(m['cluster_size']) == 0
            else:
                for m in members:
                    assert int(m['cluster_size']) == len(members), \
                        f"Cluster {cid}: stated size {m['cluster_size']}, actual {len(members)}"

    def test_min_cluster_size(self):
        """DBSCAN with minpoints=3 => every cluster has >= 3 members."""
        rows = load_result_csv('analysis_2.csv')
        clusters = {}
        for row in rows:
            cid = int(row['cluster_id'])
            if cid >= 0:
                clusters[cid] = clusters.get(cid, 0) + 1
        for cid, sz in clusters.items():
            assert sz >= 3, f"Cluster {cid} size {sz} < minpoints=3"

    def test_has_clusters(self):
        """200 random points in ~300x500km with eps=15km should form some clusters."""
        rows = load_result_csv('analysis_2.csv')
        non_noise = {int(r['cluster_id']) for r in rows} - {-1}
        assert len(non_noise) > 0, "No clusters found"


# ============================================================
# Analysis 3: River proximity
# ============================================================

class TestAnalysis3:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'analysis_3.csv'))

    def test_columns(self):
        rows = load_result_csv('analysis_3.csv')
        assert len(rows) > 0
        assert set(rows[0].keys()) == {'district_id', 'river_length_km', 'station_river_proximity_avg_m'}

    def test_row_count(self):
        rows = load_result_csv('analysis_3.csv')
        assert len(rows) == 12

    def test_most_districts_have_rivers(self):
        """Rivers span the region, so most districts should intersect at least one."""
        rows = load_result_csv('analysis_3.csv')
        with_rivers = sum(1 for r in rows if float(r['river_length_km']) > 0)
        assert with_rivers >= 8, f"Only {with_rivers}/12 districts have rivers"

    def test_reasonable_river_lengths(self):
        """Clipped river length per district should be < 500 km."""
        rows = load_result_csv('analysis_3.csv')
        for row in rows:
            length = float(row['river_length_km'])
            assert 0 <= length < 500, \
                f"District {row['district_id']}: river length {length} km unreasonable"

    def test_reasonable_proximity(self):
        rows = load_result_csv('analysis_3.csv')
        for row in rows:
            dist = float(row['station_river_proximity_avg_m'])
            assert 0 <= dist < 300000, \
                f"District {row['district_id']}: avg proximity {dist} m unreasonable"


# ============================================================
# Analysis 4: Protected area stations
# ============================================================

class TestAnalysis4:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'analysis_4.csv'))

    def test_columns(self):
        rows = load_result_csv('analysis_4.csv')
        if len(rows) > 0:
            assert set(rows[0].keys()) == {
                'station_id', 'protected_area_id', 'pollutant_reading', 'is_above_threshold'
            }

    def test_threshold_correct(self):
        """is_above_threshold must be 1 iff pollutant_reading > 75."""
        rows = load_result_csv('analysis_4.csv')
        for row in rows:
            reading = float(row['pollutant_reading'])
            flag = int(row['is_above_threshold'])
            expected = 1 if reading > 75 else 0
            assert flag == expected, \
                f"Station {row['station_id']}: reading={reading}, expected flag={expected}"

    def test_containment_independent(self):
        """Cross-validate station-in-protected-area using shapely + pyproj."""
        stations = load_stations()
        pa_gj = load_geojson('protected_areas.geojson')

        # Transform PAs from EPSG:3035 to EPSG:4326
        pa_polys = []
        for feat in pa_gj['features']:
            geom_3035 = shape(feat['geometry'])
            geom_4326 = xform(geom_3035, t_3035_to_4326)
            pa_polys.append({
                'pa_id': feat['properties']['pa_id'],
                'geom': geom_4326
            })

        # Compute expected containments
        expected_pairs = set()
        for s in stations:
            for pa in pa_polys:
                if pa['geom'].contains(s['point_4326']):
                    expected_pairs.add((s['id'], pa['pa_id']))

        # Read result
        rows = load_result_csv('analysis_4.csv')
        result_pairs = {(int(r['station_id']), r['protected_area_id']) for r in rows}

        assert result_pairs == expected_pairs, \
            f"Protected area mismatch: expected {len(expected_pairs)} pairs, got {len(result_pairs)}. " \
            f"Missing: {expected_pairs - result_pairs}, Extra: {result_pairs - expected_pairs}"


# ============================================================
# Summary JSON
# ============================================================

class TestSummary:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'summary.json'))

    def test_valid_json(self):
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_keys(self):
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            data = json.load(f)
        required = {
            'total_stations_in_protected_areas',
            'district_with_highest_avg_pollutant',
            'total_river_length_km',
            'num_clusters',
            'largest_cluster_size'
        }
        assert required.issubset(set(data.keys()))

    def test_types(self):
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            data = json.load(f)
        assert isinstance(data['total_stations_in_protected_areas'], int)
        assert isinstance(data['district_with_highest_avg_pollutant'], str)
        assert isinstance(data['total_river_length_km'], (int, float))
        assert isinstance(data['num_clusters'], int)
        assert isinstance(data['largest_cluster_size'], int)

    def test_consistency_with_analysis_4(self):
        """total_stations_in_protected_areas must match distinct stations in analysis_4."""
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            summary = json.load(f)
        rows = load_result_csv('analysis_4.csv')
        unique = len({r['station_id'] for r in rows})
        assert summary['total_stations_in_protected_areas'] == unique

    def test_consistency_with_analysis_1(self):
        """district_with_highest_avg_pollutant must match analysis_1 data."""
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            summary = json.load(f)
        rows = load_result_csv('analysis_1.csv')

        best_avg = -1
        best_did = None
        for row in rows:
            if int(row['num_stations']) > 0:
                avg = float(row['avg_pollutant'])
                if avg > best_avg:
                    best_avg = avg
                    best_did = row['district_id']

        assert summary['district_with_highest_avg_pollutant'] == best_did

    def test_consistency_with_analysis_2(self):
        """num_clusters and largest_cluster_size must match analysis_2 data."""
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            summary = json.load(f)
        rows = load_result_csv('analysis_2.csv')

        clusters = {}
        for row in rows:
            cid = int(row['cluster_id'])
            if cid >= 0:
                clusters[cid] = clusters.get(cid, 0) + 1

        assert summary['num_clusters'] == len(clusters)
        if clusters:
            assert summary['largest_cluster_size'] == max(clusters.values())

    def test_total_river_length_positive(self):
        with open(os.path.join(RESULTS_DIR, 'summary.json')) as f:
            data = json.load(f)
        assert data['total_river_length_km'] > 0
