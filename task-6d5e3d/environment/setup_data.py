#!/usr/bin/env python3
"""Create the sensor station SQLite database for the pygeoapi task."""
import sqlite3
import os

os.makedirs('/app/data', exist_ok=True)
conn = sqlite3.connect('/app/data/stations.db')
c = conn.cursor()

c.execute('''CREATE TABLE stations (
    id INTEGER PRIMARY KEY,
    station_name TEXT NOT NULL,
    station_type TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    elevation_m REAL,
    observation_time TEXT NOT NULL,
    latest_value REAL,
    status TEXT NOT NULL DEFAULT 'active'
)''')

stations = [
    # North America
    (1, "NOAA-SFO-01", "temperature", 37.7749, -122.4194, 16.0, "2024-01-15T08:00:00Z", 12.5, "active"),
    (2, "NOAA-NYC-01", "temperature", 40.7128, -74.0060, 10.0, "2024-02-20T14:30:00Z", -2.3, "active"),
    (3, "NOAA-CHI-01", "wind", 41.8781, -87.6298, 181.0, "2024-03-10T09:15:00Z", 15.7, "active"),
    (4, "NOAA-MIA-01", "precipitation", 25.7617, -80.1918, 2.0, "2024-04-05T16:45:00Z", 45.2, "active"),
    (5, "NOAA-DEN-01", "temperature", 39.7392, -104.9903, 1609.0, "2024-05-12T11:00:00Z", 8.9, "inactive"),
    # Europe
    (6, "ECMWF-LON-01", "temperature", 51.5074, -0.1278, 11.0, "2024-01-20T10:00:00Z", 5.6, "active"),
    (7, "ECMWF-PAR-01", "wind", 48.8566, 2.3522, 35.0, "2024-02-15T08:30:00Z", 12.3, "active"),
    (8, "ECMWF-BER-01", "precipitation", 52.5200, 13.4050, 34.0, "2024-03-25T14:00:00Z", 8.1, "active"),
    (9, "ECMWF-ROM-01", "temperature", 41.9028, 12.4964, 21.0, "2024-04-18T16:30:00Z", 19.4, "active"),
    (10, "ECMWF-MAD-01", "wind", 40.4168, -3.7038, 667.0, "2024-05-22T09:45:00Z", 22.1, "inactive"),
    # Asia
    (11, "JMA-TKY-01", "temperature", 35.6762, 139.6503, 40.0, "2024-01-10T07:00:00Z", 6.2, "active"),
    (12, "CMA-BEJ-01", "precipitation", 39.9042, 116.4074, 43.0, "2024-02-28T12:00:00Z", 3.5, "active"),
    (13, "IMD-DEL-01", "temperature", 28.6139, 77.2090, 216.0, "2024-03-15T10:30:00Z", 28.7, "active"),
    (14, "KMA-SEL-01", "wind", 37.5665, 126.9780, 38.0, "2024-04-10T08:00:00Z", 11.4, "active"),
    (15, "TMD-BKK-01", "precipitation", 13.7563, 100.5018, 1.5, "2024-05-30T15:00:00Z", 120.3, "active"),
    # Southern Hemisphere
    (16, "BOM-SYD-01", "temperature", -33.8688, 151.2093, 58.0, "2024-01-25T09:00:00Z", 28.1, "active"),
    (17, "SAWS-CPT-01", "wind", -33.9249, 18.4241, 0.0, "2024-02-10T11:30:00Z", 25.6, "active"),
    (18, "INMET-SPO-01", "precipitation", -23.5505, -46.6333, 760.0, "2024-03-20T13:00:00Z", 85.4, "active"),
    (19, "SMN-BUE-01", "temperature", -34.6037, -58.3816, 25.0, "2024-04-22T10:00:00Z", 16.8, "inactive"),
    (20, "NIWA-AKL-01", "wind", -36.8485, 174.7633, 0.0, "2024-05-15T08:45:00Z", 18.3, "active"),
    # Arctic / Antarctic / Remote
    (21, "AWI-NYA-01", "temperature", 78.9228, 11.9222, 8.0, "2024-01-05T06:00:00Z", -15.2, "active"),
    (22, "BAS-ROT-01", "wind", -67.5667, -68.1333, 32.0, "2024-06-01T12:00:00Z", 35.7, "active"),
    (23, "ECCC-YEL-01", "precipitation", 62.4540, -114.3718, 206.0, "2024-02-05T09:00:00Z", 1.2, "active"),
    (24, "ECCC-IQL-01", "temperature", 63.7564, -68.5170, 11.0, "2024-03-30T07:30:00Z", -8.4, "inactive"),
    (25, "AARI-TIK-01", "temperature", 71.6414, 128.8647, 8.0, "2024-04-15T05:00:00Z", -12.1, "active"),
]

c.executemany('INSERT INTO stations VALUES (?,?,?,?,?,?,?,?,?)', stations)
conn.commit()
conn.close()
print(f"Created /app/data/stations.db with {len(stations)} records")
