"""Verification tests for the geospatial water quality pipeline.

Tests both the PostgreSQL/PostGIS database structure and the
analytical results in /app/results.json.
"""

import pytest
import json
import math
import os
import csv
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

RESULTS_PATH = "/app/results.json"
DATA_DIR = "/app/data"
DB_NAME = "waterquality"


# ══════════════════════════════════════════════════════════════════════════════
# Database query helper
# ══════════════════════════════════════════════════════════════════════════════

def psql_query(query, db=DB_NAME):
    """Execute a psql query and return (stdout, returncode)."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", db, "-t", "-A", "-c", query],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip(), result.returncode


# ══════════════════════════════════════════════════════════════════════════════
# Haversine helper (reference computation)
# ══════════════════════════════════════════════════════════════════════════════

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE STRUCTURE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestDatabaseStructure:

    def test_database_accessible(self):
        out, rc = psql_query("SELECT 1")
        assert rc == 0 and out == "1", "Cannot connect to waterquality database"

    def test_postgis_enabled(self):
        out, _ = psql_query(
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis'"
        )
        assert out == "1", "PostGIS extension not enabled in waterquality database"

    def test_sites_geometry_column(self):
        out, _ = psql_query(
            "SELECT type FROM geometry_columns "
            "WHERE f_table_name = 'sites' AND f_geometry_column = 'geom'"
        )
        assert out and "POINT" in out.upper(), (
            f"sites.geom is not a POINT geometry column: '{out}'"
        )

    def test_sites_srid(self):
        out, _ = psql_query(
            "SELECT srid FROM geometry_columns "
            "WHERE f_table_name = 'sites' AND f_geometry_column = 'geom'"
        )
        assert out == "4326", f"sites.geom SRID should be 4326, got '{out}'"

    def test_stations_geometry_column(self):
        out, _ = psql_query(
            "SELECT type FROM geometry_columns "
            "WHERE f_table_name = 'stations' AND f_geometry_column = 'geom'"
        )
        assert out and "POINT" in out.upper(), (
            f"stations.geom is not a POINT geometry column: '{out}'"
        )

    def test_stations_srid(self):
        out, _ = psql_query(
            "SELECT srid FROM geometry_columns "
            "WHERE f_table_name = 'stations' AND f_geometry_column = 'geom'"
        )
        assert out == "4326", f"stations.geom SRID should be 4326, got '{out}'"

    def test_gist_index_sites(self):
        out, _ = psql_query(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'sites' AND indexdef ILIKE '%gist%'"
        )
        assert int(out) > 0, "No GiST spatial index found on sites table"

    def test_gist_index_stations(self):
        out, _ = psql_query(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'stations' AND indexdef ILIKE '%gist%'"
        )
        assert int(out) > 0, "No GiST spatial index found on stations table"

    def test_samples_table_populated(self):
        out, rc = psql_query("SELECT COUNT(*) FROM samples")
        assert rc == 0 and int(out) > 0, "samples table is empty or missing"

    def test_weather_table_populated(self):
        out, rc = psql_query("SELECT COUNT(*) FROM weather")
        assert rc == 0 and int(out) > 0, "weather table is empty or missing"

    def test_materialized_view_exists(self):
        out, _ = psql_query(
            "SELECT COUNT(*) FROM pg_matviews "
            "WHERE matviewname = 'mv_site_monthly_summary'"
        )
        assert out == "1", "Materialized view mv_site_monthly_summary not found"

    def test_materialized_view_columns(self):
        # Materialized views are NOT in information_schema.columns;
        # must query pg_attribute + pg_class instead.
        out, _ = psql_query(
            "SELECT a.attname FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "WHERE c.relname = 'mv_site_monthly_summary' "
            "AND a.attnum > 0 AND NOT a.attisdropped "
            "ORDER BY a.attname"
        )
        columns = set(out.split("\n")) if out else set()
        required = {
            "site_id", "year", "month", "sample_count",
            "exceedance_count", "exceedance_rate", "mean_bacteria",
        }
        missing = required - columns
        assert not missing, (
            f"mv_site_monthly_summary missing columns: {missing}"
        )

    def test_sites_geometry_not_null(self):
        out, _ = psql_query("SELECT COUNT(*) FROM sites WHERE geom IS NULL")
        assert out == "0", "Some sites have NULL geometry values"

    def test_stations_geometry_not_null(self):
        out, _ = psql_query("SELECT COUNT(*) FROM stations WHERE geom IS NULL")
        assert out == "0", "Some stations have NULL geometry values"


# ══════════════════════════════════════════════════════════════════════════════
# REFERENCE COMPUTATION (independent of agent's pipeline)
# ══════════════════════════════════════════════════════════════════════════════

def compute_expected():
    """Recompute all expected results from raw data files."""

    # Load site metadata
    with open(f"{DATA_DIR}/site_metadata.json") as f:
        sites = json.load(f)
    site_info = {s["site_id"]: s for s in sites}

    # Load station locations
    station_locs = {}
    with open(f"{DATA_DIR}/station_locations.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            station_locs[row["station_id"]] = (
                float(row["latitude"]),
                float(row["longitude"]),
            )

    # ── Nearest station mapping ─────────────────────────────────────────
    expected_nearest = {}
    for site in sites:
        min_dist = float("inf")
        nearest = None
        for sid, (slat, slon) in station_locs.items():
            d = haversine(site["latitude"], site["longitude"], slat, slon)
            if d < min_dist:
                min_dist = d
                nearest = sid
        expected_nearest[site["site_id"]] = nearest

    # ── Load and harmonize water quality data ───────────────────────────
    all_samples = []
    for year in range(2019, 2023):
        filepath = f"{DATA_DIR}/water_quality_{year}.csv"
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "SiteID" in row:
                    site_id = row["SiteID"]
                    date_str = row["SampleDate"]
                    bact_str = row["BacteriaCount"]
                else:
                    site_id = row["site_id"]
                    date_str = row["sample_date"]
                    bact_str = row["ecoli_cfu_per_100ml"]

                date_obj = None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        date_obj = datetime.strptime(date_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
                if date_obj is None:
                    continue

                bact_str = bact_str.strip() if bact_str else ""
                if bact_str == "":
                    continue
                if bact_str.startswith(">"):
                    bact_str = bact_str[1:]
                try:
                    bacteria = float(bact_str)
                except ValueError:
                    continue
                if bacteria <= 0:
                    continue

                all_samples.append({
                    "site_id": site_id,
                    "date": date_obj,
                    "bacteria": bacteria,
                })

    total_valid = len(all_samples)

    # ── Exceedance metrics ──────────────────────────────────────────────
    THRESHOLD = 235.0

    site_exceed_count = defaultdict(int)
    site_total_count = defaultdict(int)
    for s in all_samples:
        sid = s["site_id"]
        site_total_count[sid] += 1
        if s["bacteria"] > THRESHOLD:
            site_exceed_count[sid] += 1

    site_rates = {}
    for sid in site_total_count:
        site_rates[sid] = site_exceed_count[sid] / site_total_count[sid]

    highest_site = max(site_rates, key=site_rates.get)

    total_exceed = sum(site_exceed_count.values())
    overall_rate = round(total_exceed / total_valid, 4)

    # Marine vs freshwater
    marine_exceed = marine_total = fresh_exceed = fresh_total = 0
    for s in all_samples:
        stype = site_info[s["site_id"]]["type"]
        if stype == "marine":
            marine_total += 1
            if s["bacteria"] > THRESHOLD:
                marine_exceed += 1
        else:
            fresh_total += 1
            if s["bacteria"] > THRESHOLD:
                fresh_exceed += 1

    m_rate = marine_exceed / marine_total
    f_rate = fresh_exceed / fresh_total
    mf_ratio = round(m_rate / f_rate, 4)

    # ── Parse weather data ──────────────────────────────────────────────
    weather_precip = {}
    with open(f"{DATA_DIR}/weather_daily.fwf") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") or line.strip() == "":
                continue
            station_id = line[0:4].strip()
            date_s = line[4:14].strip()
            try:
                precip = float(line[25:33])
            except (ValueError, IndexError):
                precip = -99.9
            if precip == -99.9:
                precip = None
            weather_precip[(station_id, date_s)] = precip

    # ── Antecedent precipitation + monthly aggregation ──────────────────
    monthly_agg = defaultdict(
        lambda: {"api3_sum": 0.0, "api3_count": 0, "exc_sum": 0, "total": 0}
    )

    for s in all_samples:
        station = expected_nearest[s["site_id"]]
        precips = []
        for offset in range(1, 4):
            target = s["date"] - timedelta(days=offset)
            key = (station, target.strftime("%Y-%m-%d"))
            p = weather_precip.get(key)
            if p is not None:
                precips.append(p)
        api3 = (sum(precips) / len(precips)) if precips else None

        mkey = (s["site_id"], s["date"].year, s["date"].month)
        if api3 is not None:
            monthly_agg[mkey]["api3_sum"] += api3
            monthly_agg[mkey]["api3_count"] += 1
        monthly_agg[mkey]["exc_sum"] += 1 if s["bacteria"] > THRESHOLD else 0
        monthly_agg[mkey]["total"] += 1

    corr_x = []
    corr_y = []
    for _key, agg in monthly_agg.items():
        if agg["total"] >= 2 and agg["api3_count"] > 0:
            corr_x.append(agg["api3_sum"] / agg["api3_count"])
            corr_y.append(agg["exc_sum"] / agg["total"])

    n = len(corr_x)
    mean_x = sum(corr_x) / n
    mean_y = sum(corr_y) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(corr_x, corr_y)) / (n - 1)
    var_x = sum((x - mean_x) ** 2 for x in corr_x) / (n - 1)
    var_y = sum((y - mean_y) ** 2 for y in corr_y) / (n - 1)
    std_x = math.sqrt(var_x)
    std_y = math.sqrt(var_y)
    correlation = round(cov / (std_x * std_y), 3) if std_x > 0 and std_y > 0 else 0.0

    # ── EJ disparity ───────────────────────────────────────────────────
    high_ej_exc = high_ej_tot = low_ej_exc = low_ej_tot = 0
    for s in all_samples:
        ej = site_info[s["site_id"]]["ej_population_pct"]
        if ej >= 50:
            high_ej_tot += 1
            if s["bacteria"] > THRESHOLD:
                high_ej_exc += 1
        elif ej < 25:
            low_ej_tot += 1
            if s["bacteria"] > THRESHOLD:
                low_ej_exc += 1

    ej_ratio = round((high_ej_exc / high_ej_tot) / (low_ej_exc / low_ej_tot), 4)

    # ── Anomalous sites ────────────────────────────────────────────────
    rates = list(site_rates.values())
    mean_r = sum(rates) / len(rates)
    var_r = sum((r - mean_r) ** 2 for r in rates) / (len(rates) - 1)
    std_r = math.sqrt(var_r)
    threshold_a = mean_r + 2 * std_r
    anomalous = sorted(sid for sid, r in site_rates.items() if r > threshold_a)

    # ── Stations within 20 km (Haversine reference) ─────────────────────
    stations_within_20km = {}
    for station_id, (slat, slon) in station_locs.items():
        count = 0
        for site in sites:
            d = haversine(site["latitude"], site["longitude"], slat, slon)
            if d <= 20.0:
                count += 1
        stations_within_20km[station_id] = count

    return {
        "total_valid_samples": total_valid,
        "highest_exceedance_site": highest_site,
        "site_nearest_station": expected_nearest,
        "overall_exceedance_rate": overall_rate,
        "marine_freshwater_ratio": mf_ratio,
        "precip_exceedance_correlation": correlation,
        "ej_disparity_ratio": ej_ratio,
        "anomalous_sites": anomalous,
        "stations_within_20km": stations_within_20km,
    }


# ══════════════════════════════════════════════════════════════════════════════
# RESULTS VERIFICATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def expected():
    return compute_expected()


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"results.json not found at {RESULTS_PATH}"
    )
    with open(RESULTS_PATH) as f:
        return json.load(f)


REQUIRED_KEYS = [
    "total_valid_samples",
    "highest_exceedance_site",
    "site_nearest_station",
    "overall_exceedance_rate",
    "marine_freshwater_ratio",
    "precip_exceedance_correlation",
    "ej_disparity_ratio",
    "anomalous_sites",
    "stations_within_20km",
]


class TestResults:

    def test_results_structure(self, results):
        for key in REQUIRED_KEYS:
            assert key in results, f"Missing required key: {key}"

    def test_total_valid_samples(self, results, expected):
        assert results["total_valid_samples"] == expected["total_valid_samples"], (
            f"total_valid_samples: got {results['total_valid_samples']}, "
            f"expected {expected['total_valid_samples']}"
        )

    def test_db_sample_count_matches_json(self, results):
        out, rc = psql_query("SELECT COUNT(*) FROM samples")
        assert rc == 0, "Cannot query samples table"
        assert int(out) == results["total_valid_samples"], (
            f"DB sample count ({out}) != results.json total_valid_samples "
            f"({results['total_valid_samples']})"
        )

    def test_highest_exceedance_site(self, results, expected):
        assert results["highest_exceedance_site"] == expected["highest_exceedance_site"], (
            f"highest_exceedance_site: got {results['highest_exceedance_site']}, "
            f"expected {expected['highest_exceedance_site']}"
        )

    def test_site_nearest_station(self, results, expected):
        agent_map = results["site_nearest_station"]
        expected_map = expected["site_nearest_station"]
        assert set(agent_map.keys()) == set(expected_map.keys()), (
            "site_nearest_station has wrong set of site IDs"
        )
        for site_id in expected_map:
            assert agent_map[site_id] == expected_map[site_id], (
                f"site_nearest_station[{site_id}]: got {agent_map[site_id]}, "
                f"expected {expected_map[site_id]}"
            )

    def test_overall_exceedance_rate(self, results, expected):
        assert abs(
            results["overall_exceedance_rate"] - expected["overall_exceedance_rate"]
        ) < 0.002, (
            f"overall_exceedance_rate: got {results['overall_exceedance_rate']}, "
            f"expected {expected['overall_exceedance_rate']}"
        )

    def test_marine_freshwater_ratio(self, results, expected):
        assert abs(
            results["marine_freshwater_ratio"] - expected["marine_freshwater_ratio"]
        ) < 0.02, (
            f"marine_freshwater_ratio: got {results['marine_freshwater_ratio']}, "
            f"expected {expected['marine_freshwater_ratio']}"
        )

    def test_precip_exceedance_correlation(self, results, expected):
        assert abs(
            results["precip_exceedance_correlation"]
            - expected["precip_exceedance_correlation"]
        ) < 0.03, (
            f"precip_exceedance_correlation: got "
            f"{results['precip_exceedance_correlation']}, "
            f"expected {expected['precip_exceedance_correlation']}"
        )

    def test_ej_disparity_ratio(self, results, expected):
        assert abs(
            results["ej_disparity_ratio"] - expected["ej_disparity_ratio"]
        ) < 0.02, (
            f"ej_disparity_ratio: got {results['ej_disparity_ratio']}, "
            f"expected {expected['ej_disparity_ratio']}"
        )

    def test_anomalous_sites(self, results, expected):
        agent_anomalous = sorted(results["anomalous_sites"])
        expected_anomalous = sorted(expected["anomalous_sites"])
        assert agent_anomalous == expected_anomalous, (
            f"anomalous_sites: got {agent_anomalous}, "
            f"expected {expected_anomalous}"
        )

    def test_stations_within_20km_keys(self, results, expected):
        agent_within = results["stations_within_20km"]
        expected_within = expected["stations_within_20km"]
        assert set(agent_within.keys()) == set(expected_within.keys()), (
            f"stations_within_20km wrong station IDs: "
            f"got {set(agent_within.keys())}, "
            f"expected {set(expected_within.keys())}"
        )

    def test_stations_within_20km_counts(self, results, expected):
        agent_within = results["stations_within_20km"]
        expected_within = expected["stations_within_20km"]
        for station_id in expected_within:
            # ±1 tolerance for Haversine vs WGS84 spheroid boundary differences
            assert abs(
                int(agent_within[station_id]) - expected_within[station_id]
            ) <= 1, (
                f"stations_within_20km[{station_id}]: "
                f"got {agent_within[station_id]}, "
                f"expected {expected_within[station_id]} (±1)"
            )
