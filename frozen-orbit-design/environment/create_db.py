#!/usr/bin/env python3
"""Create the orbit design SQLite database with gravity models and mission profiles."""
import sqlite3

DB_PATH = "/app/orbit_data.db"


def create_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE gravity_models (
            model_id INTEGER PRIMARY KEY,
            model_name TEXT UNIQUE NOT NULL,
            mu_km3_s2 REAL NOT NULL,
            equatorial_radius_km REAL NOT NULL,
            flattening REAL NOT NULL,
            rotation_rate_rad_s REAL NOT NULL
        );

        CREATE TABLE zonal_harmonics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER REFERENCES gravity_models(model_id),
            degree INTEGER NOT NULL,
            coefficient REAL NOT NULL,
            UNIQUE(model_id, degree)
        );

        CREATE TABLE mission_profiles (
            profile_id INTEGER PRIMARY KEY,
            profile_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'draft', 'archived', 'suspended')),
            repeat_revolutions INTEGER NOT NULL,
            repeat_days INTEGER NOT NULL,
            target_raan_rate_deg_day REAL NOT NULL,
            altitude_min_km REAL NOT NULL,
            altitude_max_km REAL NOT NULL,
            frozen_arg_perigee_deg REAL NOT NULL,
            gravity_model_id INTEGER REFERENCES gravity_models(model_id),
            priority INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        );

        CREATE TABLE ground_stations (
            station_id INTEGER PRIMARY KEY,
            station_name TEXT NOT NULL,
            latitude_deg REAL NOT NULL,
            longitude_deg REAL NOT NULL,
            altitude_m REAL NOT NULL,
            min_elevation_deg REAL NOT NULL DEFAULT 5.0,
            network TEXT
        );

        CREATE TABLE coverage_requirements (
            requirement_id INTEGER PRIMARY KEY,
            profile_id INTEGER REFERENCES mission_profiles(profile_id),
            station_id INTEGER REFERENCES ground_stations(station_id),
            min_passes_per_repeat_cycle INTEGER NOT NULL,
            max_gap_hours REAL
        );
    """)

    # Multiple gravity models with different constants
    models = [
        (1, 'WGS84', 398600.4418, 6378.137, 3.3528107e-3, 7.2921150e-5),
        (2, 'EGM96', 398600.4415, 6378.1363, 3.3528107e-3, 7.2921151e-5),
        (3, 'JGM3', 398600.4418, 6378.137, 3.3528107e-3, 7.2921159e-5),
        (4, 'GRS80', 398600.5, 6378.137, 3.3528107e-3, 7.292115e-5),
    ]
    c.executemany("INSERT INTO gravity_models VALUES (?,?,?,?,?,?)", models)

    # Zonal harmonics per gravity model (J2 through J5)
    harmonics = [
        # WGS84 (model_id=1)
        (None, 1, 2, 1.08263e-3),
        (None, 1, 3, -2.53215e-6),
        (None, 1, 4, -1.61099e-6),
        (None, 1, 5, -2.27e-7),
        # EGM96 (model_id=2)
        (None, 2, 2, 1.08263e-3),
        (None, 2, 3, -2.53241e-6),
        (None, 2, 4, -1.61988e-6),
        (None, 2, 5, -2.27e-7),
        # JGM3 (model_id=3) — the active model
        (None, 3, 2, 0.00108262668),
        (None, 3, 3, -2.53265649e-6),
        (None, 3, 4, -1.61962e-6),
        (None, 3, 5, -2.27091e-7),
        # GRS80 (model_id=4)
        (None, 4, 2, 1.08263e-3),
        (None, 4, 3, -2.53215e-6),
        (None, 4, 4, -1.61099e-6),
        (None, 4, 5, -2.27e-7),
    ]
    c.executemany("INSERT INTO zonal_harmonics VALUES (?,?,?,?)", harmonics)

    # Multiple mission profiles — only one should be selected
    profiles = [
        (1, 'Sentinel-2A SSO', 'active', 185, 13, 0.9856473, 780.0, 820.0, 90.0,
         3, 10, '2024-01-15 10:00:00', 'Primary Earth observation mission'),
        (2, 'Landsat-9 Heritage', 'draft', 233, 16, 0.9856473, 700.0, 710.0, 90.0,
         1, 5, '2024-01-10 08:00:00', 'Landsat heritage orbit design study'),
        (3, 'TerraSAR-X Variant', 'archived', 167, 11, 0.9856473, 510.0, 520.0, 90.0,
         2, 0, '2023-12-01 14:00:00', 'SAR mission - archived'),
        (4, 'Polar Mapper', 'suspended', 211, 14, 0.9856473, 600.0, 620.0, 90.0,
         3, 8, '2024-01-12 09:00:00', 'Suspended pending instrument review'),
        (5, 'CBERS-5 Analog', 'active', 185, 13, 0.9856473, 780.0, 820.0, 90.0,
         1, 3, '2024-01-14 16:00:00', 'Lower priority duplicate — should not be selected'),
    ]
    c.executemany("INSERT INTO mission_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  profiles)

    # Polar ground station network
    stations = [
        (1, 'Svalbard SvalSat', 78.2306, 15.3894, 458.0, 5.0, 'KSAT'),
        (2, 'Kiruna', 67.8570, 20.9625, 390.0, 5.0, 'SSC'),
        (3, 'McMurdo', -77.8460, 166.6760, 24.0, 7.0, 'NASA_NEN'),
        (4, 'Troll', -72.0117, 2.5350, 1270.0, 5.0, 'KSAT'),
        (5, 'Inuvik', 68.3607, -133.7230, 103.0, 5.0, 'CSA'),
    ]
    c.executemany("INSERT INTO ground_stations VALUES (?,?,?,?,?,?,?)", stations)

    # Coverage requirements for active profile
    coverage = [
        (1, 1, 1, 26, 4.0),
        (2, 1, 2, 20, 6.0),
        (3, 1, 3, 24, 5.0),
    ]
    c.executemany("INSERT INTO coverage_requirements VALUES (?,?,?,?,?)", coverage)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_database()
    print(f"Database created at {DB_PATH}")
