#!/usr/bin/env python3
"""Solution pipeline: Load environmental monitoring data into PostgreSQL/PostGIS,
perform spatial and statistical analysis, produce /app/results.json.
"""

import json
import csv
import math
from datetime import datetime, timedelta
from collections import defaultdict

import psycopg2

DATA_DIR = "/app/data"
THRESHOLD = 235.0


# ══════════════════════════════════════════════════════════════════════════════
# Database setup
# ══════════════════════════════════════════════════════════════════════════════

def setup_database():
    """Create waterquality database with PostGIS and required schema."""
    # Connect to default postgres database to create waterquality
    conn = psycopg2.connect(dbname="postgres", user="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP DATABASE IF EXISTS waterquality")
    cur.execute("CREATE DATABASE waterquality")
    cur.close()
    conn.close()

    # Connect to waterquality and set up schema
    conn = psycopg2.connect(dbname="waterquality", user="postgres")
    cur = conn.cursor()

    # Enable PostGIS
    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    conn.commit()

    # Create tables
    cur.execute("""
        CREATE TABLE sites (
            site_id VARCHAR(10) PRIMARY KEY,
            name VARCHAR(100),
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            type VARCHAR(20),
            community VARCHAR(50),
            ej_population_pct DOUBLE PRECISION,
            geom GEOMETRY(Point, 4326)
        )
    """)

    cur.execute("""
        CREATE TABLE stations (
            station_id VARCHAR(10) PRIMARY KEY,
            name VARCHAR(100),
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            geom GEOMETRY(Point, 4326)
        )
    """)

    cur.execute("""
        CREATE TABLE samples (
            id SERIAL PRIMARY KEY,
            site_id VARCHAR(10) REFERENCES sites(site_id),
            sample_date DATE NOT NULL,
            bacteria DOUBLE PRECISION NOT NULL,
            water_temp DOUBLE PRECISION,
            year INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE weather (
            id SERIAL PRIMARY KEY,
            station_id VARCHAR(10) REFERENCES stations(station_id),
            obs_date DATE NOT NULL,
            temperature DOUBLE PRECISION,
            rel_humidity INTEGER,
            precipitation DOUBLE PRECISION,
            wind_speed DOUBLE PRECISION
        )
    """)

    # GiST spatial indices
    cur.execute("CREATE INDEX idx_sites_geom ON sites USING GIST(geom)")
    cur.execute("CREATE INDEX idx_stations_geom ON stations USING GIST(geom)")

    # Regular indices for query performance
    cur.execute("CREATE INDEX idx_samples_site ON samples(site_id)")
    cur.execute("CREATE INDEX idx_samples_date ON samples(sample_date)")
    cur.execute(
        "CREATE INDEX idx_weather_station_date ON weather(station_id, obs_date)"
    )

    conn.commit()
    return conn, cur


# ══════════════════════════════════════════════════════════════════════════════
# Data loading
# ══════════════════════════════════════════════════════════════════════════════

def load_sites(cur):
    """Load site metadata with PostGIS geometry."""
    with open(f"{DATA_DIR}/site_metadata.json") as f:
        sites = json.load(f)
    for s in sites:
        cur.execute(
            "INSERT INTO sites "
            "(site_id, name, latitude, longitude, type, community, "
            "ej_population_pct, geom) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, "
            "ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
            (s["site_id"], s["name"], s["latitude"], s["longitude"],
             s["type"], s["community"], s["ej_population_pct"],
             s["longitude"], s["latitude"]),
        )
    print(f"  Loaded {len(sites)} sites")


def load_stations(cur):
    """Load weather station data with PostGIS geometry."""
    count = 0
    with open(f"{DATA_DIR}/station_locations.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute(
                "INSERT INTO stations "
                "(station_id, name, latitude, longitude, geom) "
                "VALUES (%s, %s, %s, %s, "
                "ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                (row["station_id"], row["name"],
                 float(row["latitude"]), float(row["longitude"]),
                 float(row["longitude"]), float(row["latitude"])),
            )
            count += 1
    print(f"  Loaded {count} stations")


def load_samples(cur):
    """Load and harmonize water quality samples from all years."""
    count = 0
    for year in range(2019, 2023):
        filepath = f"{DATA_DIR}/water_quality_{year}.csv"
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Harmonize column names across schema versions
                if "SiteID" in row:
                    site_id = row["SiteID"]
                    date_str = row["SampleDate"]
                    bact_str = row["BacteriaCount"]
                    temp_str = row.get("WaterTemp", "")
                else:
                    site_id = row["site_id"]
                    date_str = row["sample_date"]
                    bact_str = row["ecoli_cfu_per_100ml"]
                    temp_str = row.get("water_temp_celsius", "")

                # Parse date (two formats across years)
                date_obj = None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        date_obj = datetime.strptime(date_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
                if date_obj is None:
                    continue

                # Parse bacteria count (handle '>' prefix, missing, negatives)
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

                # Parse water temperature
                try:
                    water_temp = float(temp_str) if temp_str and temp_str.strip() else None
                except (ValueError, TypeError):
                    water_temp = None

                cur.execute(
                    "INSERT INTO samples "
                    "(site_id, sample_date, bacteria, water_temp, year) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (site_id, date_obj.date(), bacteria, water_temp, year),
                )
                count += 1

    print(f"  Loaded {count} valid samples")
    return count


def load_weather(cur):
    """Parse fixed-width weather data and load into database."""
    count = 0
    with open(f"{DATA_DIR}/weather_daily.fwf") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") or line.strip() == "":
                continue

            station_id = line[0:4].strip()
            date_str = line[4:14].strip()

            try:
                obs_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            # Parse fields, convert sentinel values to None (SQL NULL)
            try:
                temp = float(line[14:21])
                temp = None if temp == -99.9 else temp
            except (ValueError, IndexError):
                temp = None

            try:
                rh = int(line[21:25])
                rh = None if rh == -9 else rh
            except (ValueError, IndexError):
                rh = None

            try:
                precip = float(line[25:33])
                precip = None if precip == -99.9 else precip
            except (ValueError, IndexError):
                precip = None

            try:
                wind = float(line[33:39])
                wind = None if wind == -9.9 else wind
            except (ValueError, IndexError):
                wind = None

            cur.execute(
                "INSERT INTO weather "
                "(station_id, obs_date, temperature, rel_humidity, "
                "precipitation, wind_speed) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (station_id, obs_date, temp, rh, precip, wind),
            )
            count += 1

    print(f"  Loaded {count} weather records")


def create_materialized_view(cur):
    """Create site-monthly summary materialized view."""
    cur.execute("""
        CREATE MATERIALIZED VIEW mv_site_monthly_summary AS
        SELECT
            site_id,
            EXTRACT(YEAR FROM sample_date)::INTEGER AS year,
            EXTRACT(MONTH FROM sample_date)::INTEGER AS month,
            COUNT(*)::INTEGER AS sample_count,
            SUM(CASE WHEN bacteria > 235 THEN 1 ELSE 0 END)::INTEGER
                AS exceedance_count,
            ROUND(
                SUM(CASE WHEN bacteria > 235 THEN 1.0 ELSE 0.0 END)::NUMERIC
                / COUNT(*)::NUMERIC, 4
            ) AS exceedance_rate,
            ROUND(AVG(bacteria)::NUMERIC, 2) AS mean_bacteria
        FROM samples
        GROUP BY site_id,
                 EXTRACT(YEAR FROM sample_date),
                 EXTRACT(MONTH FROM sample_date)
    """)
    print("  Created materialized view mv_site_monthly_summary")


# ══════════════════════════════════════════════════════════════════════════════
# Analysis
# ══════════════════════════════════════════════════════════════════════════════

def compute_results(cur):
    """Run all analyses using PostGIS and SQL, return results dict."""
    results = {}

    # ── Total valid samples ─────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM samples")
    results["total_valid_samples"] = cur.fetchone()[0]

    # ── Nearest station via PostGIS geography distance ──────────────────
    cur.execute("""
        SELECT s.site_id,
               (SELECT st.station_id
                FROM stations st
                ORDER BY s.geom::geography <-> st.geom::geography
                LIMIT 1) AS nearest_station
        FROM sites s
        ORDER BY s.site_id
    """)
    nearest_map = {row[0]: row[1] for row in cur.fetchall()}
    results["site_nearest_station"] = nearest_map

    # ── Per-site exceedance rates ───────────────────────────────────────
    cur.execute("""
        SELECT site_id,
               SUM(CASE WHEN bacteria > 235 THEN 1 ELSE 0 END)::FLOAT
               / COUNT(*) AS rate
        FROM samples
        GROUP BY site_id
    """)
    site_rates = {row[0]: row[1] for row in cur.fetchall()}
    results["highest_exceedance_site"] = max(site_rates, key=site_rates.get)

    # ── Overall exceedance rate ─────────────────────────────────────────
    cur.execute("""
        SELECT ROUND(
            SUM(CASE WHEN bacteria > 235 THEN 1 ELSE 0 END)::NUMERIC
            / COUNT(*)::NUMERIC, 4
        ) FROM samples
    """)
    results["overall_exceedance_rate"] = float(cur.fetchone()[0])

    # ── Marine / freshwater ratio ───────────────────────────────────────
    cur.execute("""
        SELECT ROUND(
            (SELECT SUM(CASE WHEN sm.bacteria > 235 THEN 1 ELSE 0 END)::NUMERIC
                    / COUNT(*)
             FROM samples sm
             JOIN sites si ON sm.site_id = si.site_id
             WHERE si.type = 'marine')
            /
            (SELECT SUM(CASE WHEN sm.bacteria > 235 THEN 1 ELSE 0 END)::NUMERIC
                    / COUNT(*)
             FROM samples sm
             JOIN sites si ON sm.site_id = si.site_id
             WHERE si.type = 'freshwater'),
            4
        )
    """)
    results["marine_freshwater_ratio"] = float(cur.fetchone()[0])

    # ── API-3 correlation (hybrid SQL + Python) ─────────────────────────
    # Fetch weather precipitation lookup
    cur.execute(
        "SELECT station_id, obs_date, precipitation "
        "FROM weather WHERE precipitation IS NOT NULL"
    )
    weather_precip = {}
    for station_id, obs_date, precip in cur.fetchall():
        weather_precip[(station_id, str(obs_date))] = float(precip)

    # Fetch all samples
    cur.execute("SELECT site_id, sample_date, bacteria FROM samples")
    all_samples = cur.fetchall()

    # Monthly aggregation
    monthly_agg = defaultdict(
        lambda: {"api3_sum": 0.0, "api3_count": 0, "exc_sum": 0, "total": 0}
    )
    for site_id, sample_date, bacteria in all_samples:
        station = nearest_map[site_id]
        precips = []
        for offset in range(1, 4):
            target = sample_date - timedelta(days=offset)
            key = (station, str(target))
            p = weather_precip.get(key)
            if p is not None:
                precips.append(p)
        api3 = (sum(precips) / len(precips)) if precips else None

        mkey = (site_id, sample_date.year, sample_date.month)
        if api3 is not None:
            monthly_agg[mkey]["api3_sum"] += api3
            monthly_agg[mkey]["api3_count"] += 1
        monthly_agg[mkey]["exc_sum"] += 1 if bacteria > THRESHOLD else 0
        monthly_agg[mkey]["total"] += 1

    corr_x, corr_y = [], []
    for agg in monthly_agg.values():
        if agg["total"] >= 2 and agg["api3_count"] > 0:
            corr_x.append(agg["api3_sum"] / agg["api3_count"])
            corr_y.append(agg["exc_sum"] / agg["total"])

    # Manual Pearson r
    n = len(corr_x)
    mean_x = sum(corr_x) / n
    mean_y = sum(corr_y) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(corr_x, corr_y)) / (n - 1)
    var_x = sum((x - mean_x) ** 2 for x in corr_x) / (n - 1)
    var_y = sum((y - mean_y) ** 2 for y in corr_y) / (n - 1)
    std_x = math.sqrt(var_x)
    std_y = math.sqrt(var_y)
    results["precip_exceedance_correlation"] = (
        round(cov / (std_x * std_y), 3) if std_x > 0 and std_y > 0 else 0.0
    )

    # ── EJ disparity ratio ─────────────────────────────────────────────
    cur.execute("""
        SELECT ROUND(
            (SELECT SUM(CASE WHEN sm.bacteria > 235 THEN 1 ELSE 0 END)::NUMERIC
                    / COUNT(*)
             FROM samples sm
             JOIN sites si ON sm.site_id = si.site_id
             WHERE si.ej_population_pct >= 50)
            /
            (SELECT SUM(CASE WHEN sm.bacteria > 235 THEN 1 ELSE 0 END)::NUMERIC
                    / COUNT(*)
             FROM samples sm
             JOIN sites si ON sm.site_id = si.site_id
             WHERE si.ej_population_pct < 25),
            4
        )
    """)
    results["ej_disparity_ratio"] = float(cur.fetchone()[0])

    # ── Anomalous sites (mean + 2 * sample std dev) ────────────────────
    rates = list(site_rates.values())
    mean_r = sum(rates) / len(rates)
    var_r = sum((r - mean_r) ** 2 for r in rates) / (len(rates) - 1)
    std_r = math.sqrt(var_r)
    threshold_a = mean_r + 2 * std_r
    results["anomalous_sites"] = sorted(
        sid for sid, r in site_rates.items() if r > threshold_a
    )

    # ── Stations within 20 km (PostGIS ST_DWithin) ─────────────────────
    cur.execute("""
        SELECT st.station_id,
               (SELECT COUNT(DISTINCT s.site_id)
                FROM sites s
                WHERE ST_DWithin(
                    st.geom::geography, s.geom::geography, 20000
                ))::INTEGER AS site_count
        FROM stations st
        ORDER BY st.station_id
    """)
    results["stations_within_20km"] = {row[0]: row[1] for row in cur.fetchall()}

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Setting up database...")
    conn, cur = setup_database()

    print("Loading data...")
    load_sites(cur)
    load_stations(cur)
    load_samples(cur)
    load_weather(cur)
    conn.commit()

    print("Creating materialized view...")
    create_materialized_view(cur)
    conn.commit()

    print("Computing results...")
    results = compute_results(cur)

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    print(json.dumps(results, indent=2))

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
