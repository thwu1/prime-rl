"""Tests for the Noto Peninsula earthquake sequence analysis pipeline.

Independently loads the same GeoJSON catalog, applies identical filtering
and computations, and verifies the agent's outputs against reference values.
"""

import json
import math
import os
import sqlite3
import statistics

import pytest

CATALOG_PATH = "/app/data/catalog.json"
DB_PATH = "/app/noto_seismic.db"
ANALYSIS_PATH = "/app/analysis.json"

NOTO_LAT_MIN = 36.5
NOTO_LAT_MAX = 38.5
NOTO_LON_MIN = 136.0
NOTO_LON_MAX = 138.5
EARTH_RADIUS = 6371.0
BIN_WIDTH = 0.1


def haversine(lat1, lon1, lat2, lon2):
    """Haversine great-circle distance in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_reference_events():
    """Load GeoJSON catalog and filter to Noto bounding box."""
    with open(CATALOG_PATH) as f:
        data = json.load(f)

    events = []
    for feat in data["features"]:
        p = feat["properties"]
        c = feat["geometry"]["coordinates"]
        lon, lat, depth = c[0], c[1], c[2]
        if NOTO_LAT_MIN <= lat <= NOTO_LAT_MAX and NOTO_LON_MIN <= lon <= NOTO_LON_MAX:
            events.append(
                {
                    "id": feat["id"],
                    "time_ms": p["time"],
                    "latitude": lat,
                    "longitude": lon,
                    "depth_km": depth,
                    "magnitude": p["mag"],
                    "mag_type": p.get("magType", ""),
                    "place": p.get("place", ""),
                }
            )
    events.sort(key=lambda e: e["time_ms"])
    return events


def compute_mc_reference(magnitudes):
    """Completeness magnitude via Maximum Curvature."""
    mag_min = round(math.floor(min(magnitudes) * 10) / 10.0, 1)
    mag_max = round(math.ceil(max(magnitudes) * 10) / 10.0, 1)

    bins = {}
    current = mag_min
    while current <= mag_max + 0.001:
        bins[round(current, 1)] = 0
        current += BIN_WIDTH

    for m in magnitudes:
        bv = round(math.floor(m * 10) / 10.0, 1)
        if bv in bins:
            bins[bv] += 1

    return max(bins, key=bins.get)


def compute_energy(magnitude):
    """Gutenberg-Richter energy-magnitude relation: log10(E) = 1.5*M + 4.8 (Joules)."""
    return 10 ** (1.5 * magnitude + 4.8)


@pytest.fixture(scope="module")
def ref_events():
    return load_reference_events()


@pytest.fixture(scope="module")
def analysis():
    with open(ANALYSIS_PATH) as f:
        return json.load(f)


# ────────────────────── Structure Tests ──────────────────────


class TestFileExistence:
    def test_analysis_json_exists(self):
        assert os.path.exists(ANALYSIS_PATH), "analysis.json not found at /app/analysis.json"

    def test_database_exists(self):
        assert os.path.exists(DB_PATH), "noto_seismic.db not found at /app/noto_seismic.db"


class TestAnalysisKeys:
    def test_top_level_keys(self, analysis):
        required = [
            "event_count",
            "mainshock",
            "largest_aftershock",
            "bath_law_delta",
            "foreshock_count",
            "mc",
            "b_value",
            "b_value_uncertainty",
            "a_value",
            "omori",
            "aftershock_zone_length_km",
            "total_energy_joules",
            "mainshock_energy_fraction",
            "median_interevent_distance_km",
            "mean_interevent_distance_km",
            "spatial_density",
        ]
        for key in required:
            assert key in analysis, f"Missing top-level key: {key}"

    def test_mainshock_keys(self, analysis):
        required = ["id", "magnitude", "latitude", "longitude", "depth_km", "time_ms"]
        for key in required:
            assert key in analysis["mainshock"], f"mainshock missing key: {key}"
            assert key in analysis["largest_aftershock"], f"largest_aftershock missing key: {key}"

    def test_omori_keys(self, analysis):
        for key in ["K", "c", "p"]:
            assert key in analysis["omori"], f"omori missing key: {key}"

    def test_spatial_density_keys(self, analysis):
        for key in ["grid_cell_lat_min", "grid_cell_lon_min", "count"]:
            assert key in analysis["spatial_density"], f"spatial_density missing key: {key}"


# ────────────────────── Database Schema Tests ──────────────────────


class TestDatabaseSchema:
    def test_events_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
        assert cur.fetchone() is not None, "events table not found"
        conn.close()

    def test_interevent_distances_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='interevent_distances'"
        )
        assert cur.fetchone() is not None, "interevent_distances table not found"
        conn.close()

    def test_events_columns(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(events)")
        cols = {row[1] for row in cur.fetchall()}
        required = {
            "id",
            "time_ms",
            "latitude",
            "longitude",
            "depth_km",
            "magnitude",
            "mag_type",
            "place",
            "gap",
            "dmin",
            "rms",
            "sig",
            "status",
            "tsunami",
        }
        missing = required - cols
        assert not missing, f"events table missing columns: {missing}"
        conn.close()

    def test_interevent_columns(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(interevent_distances)")
        cols = {row[1] for row in cur.fetchall()}
        required = {"event1_id", "event2_id", "distance_km", "time_diff_sec"}
        missing = required - cols
        assert not missing, f"interevent_distances table missing columns: {missing}"
        conn.close()

    def test_event_row_count(self, ref_events):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM events")
        db_count = cur.fetchone()[0]
        conn.close()
        assert db_count == len(ref_events), (
            f"DB has {db_count} events, expected {len(ref_events)}"
        )

    def test_interevent_row_count(self, ref_events):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM interevent_distances")
        count = cur.fetchone()[0]
        conn.close()
        assert count == len(ref_events) - 1, (
            f"interevent_distances has {count} rows, expected {len(ref_events) - 1}"
        )


# ────────────────────── Event Count Test ──────────────────────


class TestEventCount:
    def test_event_count_correct(self, analysis, ref_events):
        assert analysis["event_count"] == len(ref_events), (
            f"event_count={analysis['event_count']}, expected={len(ref_events)}"
        )


# ────────────────────── Mainshock Tests ──────────────────────


class TestMainshock:
    def test_mainshock_id(self, analysis):
        assert analysis["mainshock"]["id"] == "us6000m0xl", (
            f"mainshock id={analysis['mainshock']['id']}, expected us6000m0xl"
        )

    def test_mainshock_magnitude(self, analysis):
        assert abs(analysis["mainshock"]["magnitude"] - 7.5) < 0.01

    def test_mainshock_is_largest(self, analysis, ref_events):
        max_mag = max(e["magnitude"] for e in ref_events)
        assert abs(analysis["mainshock"]["magnitude"] - max_mag) < 0.01


# ────────────────────── Largest Aftershock Tests ──────────────────────


class TestLargestAftershock:
    def test_aftershock_after_mainshock(self, analysis):
        assert analysis["largest_aftershock"]["time_ms"] > analysis["mainshock"]["time_ms"], (
            "largest aftershock must occur after mainshock"
        )

    def test_largest_aftershock_magnitude(self, analysis, ref_events):
        mainshock_time = max(ref_events, key=lambda e: e["magnitude"])["time_ms"]
        aftershocks = [e for e in ref_events if e["time_ms"] > mainshock_time]
        expected_mag = max(e["magnitude"] for e in aftershocks)
        assert abs(analysis["largest_aftershock"]["magnitude"] - expected_mag) < 0.01, (
            f"largest_aftershock mag={analysis['largest_aftershock']['magnitude']}, "
            f"expected={expected_mag}"
        )

    def test_largest_aftershock_id(self, analysis, ref_events):
        mainshock_time = max(ref_events, key=lambda e: e["magnitude"])["time_ms"]
        aftershocks = [e for e in ref_events if e["time_ms"] > mainshock_time]
        expected = max(aftershocks, key=lambda e: e["magnitude"])
        assert analysis["largest_aftershock"]["id"] == expected["id"]


# ────────────────────── Bath's Law Test ──────────────────────


class TestBathLaw:
    def test_bath_law_delta(self, analysis):
        expected = analysis["mainshock"]["magnitude"] - analysis["largest_aftershock"]["magnitude"]
        assert abs(analysis["bath_law_delta"] - expected) < 0.01, (
            f"bath_law_delta={analysis['bath_law_delta']}, expected={expected}"
        )

    def test_bath_law_positive(self, analysis):
        assert analysis["bath_law_delta"] > 0, "bath_law_delta must be positive"


# ────────────────────── Foreshock Tests ──────────────────────


class TestForeshocks:
    def test_foreshock_count_correct(self, analysis, ref_events):
        mainshock = max(ref_events, key=lambda e: e["magnitude"])
        expected = sum(1 for e in ref_events if e["time_ms"] < mainshock["time_ms"])
        assert analysis["foreshock_count"] == expected, (
            f"foreshock_count={analysis['foreshock_count']}, expected={expected}"
        )

    def test_foreshock_count_nonnegative(self, analysis):
        assert analysis["foreshock_count"] >= 0, "foreshock_count must be non-negative"


# ────────────────────── Gutenberg-Richter Tests ──────────────────────


class TestGutenbergRichter:
    def test_mc_correct(self, analysis, ref_events):
        magnitudes = [e["magnitude"] for e in ref_events]
        expected_mc = compute_mc_reference(magnitudes)
        assert abs(analysis["mc"] - expected_mc) < 0.05, (
            f"mc={analysis['mc']}, expected={expected_mc}"
        )

    def test_b_value_correct(self, analysis, ref_events):
        magnitudes = [e["magnitude"] for e in ref_events]
        mc = compute_mc_reference(magnitudes)
        filtered = [m for m in magnitudes if m >= mc]
        m_mean = statistics.mean(filtered)
        expected_b = math.log10(math.e) / (m_mean - (mc - BIN_WIDTH / 2))
        assert abs(analysis["b_value"] - expected_b) < 0.1, (
            f"b_value={analysis['b_value']}, expected={expected_b}"
        )

    def test_b_value_physical_range(self, analysis):
        assert 0.3 < analysis["b_value"] < 3.0, (
            f"b_value={analysis['b_value']} outside physical range [0.3, 3.0]"
        )

    def test_a_value_correct(self, analysis, ref_events):
        magnitudes = [e["magnitude"] for e in ref_events]
        mc = compute_mc_reference(magnitudes)
        n = len([m for m in magnitudes if m >= mc])
        expected_a = math.log10(n)
        assert abs(analysis["a_value"] - expected_a) < 0.1, (
            f"a_value={analysis['a_value']}, expected={expected_a}"
        )

    def test_b_value_uncertainty_correct(self, analysis, ref_events):
        magnitudes = [e["magnitude"] for e in ref_events]
        mc = compute_mc_reference(magnitudes)
        filtered = [m for m in magnitudes if m >= mc]
        n = len(filtered)
        m_mean = statistics.mean(filtered)
        b = math.log10(math.e) / (m_mean - (mc - BIN_WIDTH / 2))
        sigma = statistics.stdev(filtered)
        expected_db = 2.30 * b ** 2 * sigma / math.sqrt(n)
        assert abs(analysis["b_value_uncertainty"] - expected_db) < 0.05, (
            f"b_value_uncertainty={analysis['b_value_uncertainty']}, expected={expected_db}"
        )

    def test_b_value_uncertainty_positive(self, analysis):
        assert analysis["b_value_uncertainty"] > 0, "b_value_uncertainty must be positive"


# ────────────────────── Omori's Law Tests ──────────────────────


class TestOmoriLaw:
    def test_omori_p_range(self, analysis):
        p = analysis["omori"]["p"]
        assert 0.3 < p < 3.0, f"Omori p={p} outside expected range [0.3, 3.0]"

    def test_omori_c_positive(self, analysis):
        assert analysis["omori"]["c"] > 0, f"Omori c={analysis['omori']['c']} must be positive"

    def test_omori_k_positive(self, analysis):
        assert analysis["omori"]["K"] > 0, f"Omori K={analysis['omori']['K']} must be positive"

    def test_omori_fit_reasonable(self, analysis, ref_events):
        """Verify the Omori fit produces non-trivial parameters."""
        mainshock = max(ref_events, key=lambda e: e["magnitude"])
        aftershock_count = sum(
            1 for e in ref_events if e["time_ms"] > mainshock["time_ms"]
        )
        max_time_hrs = max(
            (e["time_ms"] - mainshock["time_ms"]) / 3600000.0
            for e in ref_events
            if e["time_ms"] > mainshock["time_ms"]
        )
        avg_rate = aftershock_count / max(max_time_hrs, 1)
        assert analysis["omori"]["K"] > avg_rate * 0.1, (
            f"Omori K={analysis['omori']['K']} seems too small for "
            f"avg_rate={avg_rate:.2f}"
        )


# ────────────────────── Aftershock Zone Length Tests ──────────────────────


class TestAftershockZoneLength:
    def test_zone_length_correct(self, analysis, ref_events):
        mainshock = max(ref_events, key=lambda e: e["magnitude"])
        aftershocks = [e for e in ref_events if e["time_ms"] > mainshock["time_ms"]]
        max_dist = 0.0
        for i in range(len(aftershocks)):
            for j in range(i + 1, len(aftershocks)):
                d = haversine(
                    aftershocks[i]["latitude"],
                    aftershocks[i]["longitude"],
                    aftershocks[j]["latitude"],
                    aftershocks[j]["longitude"],
                )
                if d > max_dist:
                    max_dist = d
        assert abs(analysis["aftershock_zone_length_km"] - max_dist) < 1.0, (
            f"aftershock_zone_length_km={analysis['aftershock_zone_length_km']}, "
            f"expected={max_dist}"
        )

    def test_zone_length_positive(self, analysis):
        assert analysis["aftershock_zone_length_km"] > 0, (
            "aftershock_zone_length_km must be positive"
        )


# ────────────────────── Energy Tests ──────────────────────


class TestEnergy:
    def test_total_energy_correct(self, analysis, ref_events):
        expected = sum(compute_energy(e["magnitude"]) for e in ref_events)
        ratio = analysis["total_energy_joules"] / expected
        assert 0.99 < ratio < 1.01, (
            f"total_energy_joules={analysis['total_energy_joules']:.3e}, "
            f"expected={expected:.3e}"
        )

    def test_mainshock_energy_fraction_correct(self, analysis, ref_events):
        mainshock = max(ref_events, key=lambda e: e["magnitude"])
        total = sum(compute_energy(e["magnitude"]) for e in ref_events)
        expected_frac = compute_energy(mainshock["magnitude"]) / total
        assert abs(analysis["mainshock_energy_fraction"] - expected_frac) < 0.01, (
            f"mainshock_energy_fraction={analysis['mainshock_energy_fraction']}, "
            f"expected={expected_frac}"
        )

    def test_mainshock_energy_dominates(self, analysis):
        """The mainshock should contribute the vast majority of seismic energy."""
        assert analysis["mainshock_energy_fraction"] > 0.9, (
            f"mainshock_energy_fraction={analysis['mainshock_energy_fraction']} "
            "expected > 0.9 for M7.5 dominant event"
        )

    def test_total_energy_positive(self, analysis):
        assert analysis["total_energy_joules"] > 0, "total_energy_joules must be positive"


# ────────────────────── Interevent Distance Tests ──────────────────────


class TestIntereventDistances:
    def _compute_reference_distances(self, ref_events):
        distances = []
        for i in range(len(ref_events) - 1):
            e1, e2 = ref_events[i], ref_events[i + 1]
            d = haversine(
                e1["latitude"], e1["longitude"], e2["latitude"], e2["longitude"]
            )
            distances.append(d)
        return distances

    def test_median_distance(self, analysis, ref_events):
        dists = self._compute_reference_distances(ref_events)
        expected = statistics.median(dists)
        assert abs(analysis["median_interevent_distance_km"] - expected) < 1.0, (
            f"median={analysis['median_interevent_distance_km']:.3f}, expected={expected:.3f}"
        )

    def test_mean_distance(self, analysis, ref_events):
        dists = self._compute_reference_distances(ref_events)
        expected = statistics.mean(dists)
        assert abs(analysis["mean_interevent_distance_km"] - expected) < 1.0, (
            f"mean={analysis['mean_interevent_distance_km']:.3f}, expected={expected:.3f}"
        )

    def test_distances_nonnegative(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT MIN(distance_km) FROM interevent_distances")
        min_dist = cur.fetchone()[0]
        conn.close()
        assert min_dist >= 0, f"Found negative distance: {min_dist}"

    def test_time_diffs_nonnegative(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT MIN(time_diff_sec) FROM interevent_distances")
        min_td = cur.fetchone()[0]
        conn.close()
        assert min_td >= 0, f"Found negative time_diff_sec: {min_td}"

    def test_db_distances_match_haversine(self, ref_events):
        """Spot-check first 5 DB distances against independent Haversine computation."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT event1_id, event2_id, distance_km FROM interevent_distances LIMIT 5"
        )
        rows = cur.fetchall()
        conn.close()

        id_to_event = {e["id"]: e for e in ref_events}
        for e1_id, e2_id, db_dist in rows:
            if e1_id in id_to_event and e2_id in id_to_event:
                e1, e2 = id_to_event[e1_id], id_to_event[e2_id]
                expected = haversine(
                    e1["latitude"], e1["longitude"], e2["latitude"], e2["longitude"]
                )
                assert abs(db_dist - expected) < 0.5, (
                    f"DB distance {e1_id}->{e2_id}: {db_dist:.3f}, "
                    f"expected {expected:.3f}"
                )


# ────────────────────── Spatial Density Tests ──────────────────────


class TestSpatialDensity:
    def _compute_reference_grid(self, ref_events):
        grid = {}
        for e in ref_events:
            lat_bin = math.floor(e["latitude"] / 0.5) * 0.5
            lon_bin = math.floor(e["longitude"] / 0.5) * 0.5
            key = (lat_bin, lon_bin)
            grid[key] = grid.get(key, 0) + 1
        densest = max(grid, key=grid.get)
        return densest, grid[densest]

    def test_densest_cell_location(self, analysis, ref_events):
        (exp_lat, exp_lon), _ = self._compute_reference_grid(ref_events)
        assert abs(analysis["spatial_density"]["grid_cell_lat_min"] - exp_lat) < 0.01, (
            f"grid_cell_lat_min={analysis['spatial_density']['grid_cell_lat_min']}, "
            f"expected={exp_lat}"
        )
        assert abs(analysis["spatial_density"]["grid_cell_lon_min"] - exp_lon) < 0.01, (
            f"grid_cell_lon_min={analysis['spatial_density']['grid_cell_lon_min']}, "
            f"expected={exp_lon}"
        )

    def test_densest_cell_count(self, analysis, ref_events):
        _, exp_count = self._compute_reference_grid(ref_events)
        assert analysis["spatial_density"]["count"] == exp_count, (
            f"count={analysis['spatial_density']['count']}, expected={exp_count}"
        )
