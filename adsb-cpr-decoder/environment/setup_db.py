#!/usr/bin/env python3
"""Create the aircraft state database for the ADS-B encoder task."""

import sqlite3
import random

db = sqlite3.connect('/app/aircraft.db')
c = db.cursor()

# Core encoding tables
c.execute('''CREATE TABLE aircraft (
    icao TEXT PRIMARY KEY,
    callsign TEXT NOT NULL
)''')

c.execute('''CREATE TABLE positions (
    icao TEXT PRIMARY KEY REFERENCES aircraft(icao),
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude_ft INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE velocities (
    icao TEXT PRIMARY KEY REFERENCES aircraft(icao),
    ground_speed_kt REAL NOT NULL,
    heading_deg REAL NOT NULL,
    vertical_rate_fpm INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE error_injection (
    icao TEXT REFERENCES aircraft(icao),
    message_type TEXT NOT NULL,
    bit_position INTEGER NOT NULL
)''')

# Operational context tables
c.execute('''CREATE TABLE transponder_config (
    icao TEXT PRIMARY KEY REFERENCES aircraft(icao),
    mode_s_level TEXT NOT NULL,
    adsb_version INTEGER NOT NULL,
    sil INTEGER NOT NULL,
    sda INTEGER NOT NULL,
    nic_supplement INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE flight_metadata (
    icao TEXT PRIMARY KEY REFERENCES aircraft(icao),
    flight_number TEXT,
    departure_icao TEXT,
    arrival_icao TEXT,
    squawk TEXT,
    route TEXT
)''')

c.execute('''CREATE TABLE surveillance_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icao TEXT REFERENCES aircraft(icao),
    timestamp_utc TEXT NOT NULL,
    signal_dbm REAL,
    range_nm REAL,
    receiver_id TEXT
)''')

c.execute('''CREATE VIEW aircraft_state_view AS
    SELECT a.icao, a.callsign,
           p.latitude, p.longitude, p.altitude_ft,
           v.ground_speed_kt, v.heading_deg, v.vertical_rate_fpm,
           t.mode_s_level, t.adsb_version, t.sil, t.sda,
           f.flight_number, f.squawk
    FROM aircraft a
    LEFT JOIN positions p ON a.icao = p.icao
    LEFT JOIN velocities v ON a.icao = v.icao
    LEFT JOIN transponder_config t ON a.icao = t.icao
    LEFT JOIN flight_metadata f ON a.icao = f.icao
''')

# Populate core tables
aircraft_data = [
    ('A1B2C3', 'TEST01'),
    ('D4E5F6', 'BENCH2'),
    ('789ABC', 'EVAL03'),
    ('1A2B3C', 'QUIZ4X'),
    ('FE9876', 'HARD05'),
    ('C0FFEE', 'EDGE06'),
]
c.executemany('INSERT INTO aircraft VALUES (?,?)', aircraft_data)

position_data = [
    ('A1B2C3', 40.0, -74.0, 35000),
    ('D4E5F6', 51.5, -0.1, 28000),
    ('789ABC', -33.9, 151.2, 41000),
    ('1A2B3C', 35.7, 139.7, 15000),
    ('FE9876', 82.0, 10.0, 42000),
    ('C0FFEE', -0.5, -179.9, 1000),
]
c.executemany('INSERT INTO positions VALUES (?,?,?,?)', position_data)

velocity_data = [
    ('A1B2C3', 450.0, 90.0, 0),
    ('D4E5F6', 380.0, 270.0, -512),
    ('789ABC', 510.0, 180.0, 0),
    ('1A2B3C', 249.0, 45.0, 2048),
    ('FE9876', 300.0, 0.0, 0),
    ('C0FFEE', 150.0, 315.0, -1024),
]
c.executemany('INSERT INTO velocities VALUES (?,?,?,?)', velocity_data)

error_data = [
    ('A1B2C3', 'position_even', 50),
    ('789ABC', 'velocity', 80),
]
c.executemany('INSERT INTO error_injection VALUES (?,?,?)', error_data)

# Populate operational context tables
transponder_data = [
    ('A1B2C3', 'ELS', 2, 3, 2, 0),
    ('D4E5F6', 'EHS', 2, 3, 2, 1),
    ('789ABC', 'ELS', 1, 2, 1, 0),
    ('1A2B3C', 'EHS', 2, 3, 2, 0),
    ('FE9876', 'ELS', 2, 2, 1, 1),
    ('C0FFEE', 'EHS', 0, 1, 1, 0),
]
c.executemany('INSERT INTO transponder_config VALUES (?,?,?,?,?,?)',
              transponder_data)

flight_data = [
    ('A1B2C3', 'TST001', 'KJFK', 'EGLL', '1200', 'KJFK DCT NATB DCT EGLL'),
    ('D4E5F6', 'BN002', 'EGLL', 'KJFK', '2345', 'EGLL DCT NATA DCT KJFK'),
    ('789ABC', 'EV003', 'YSSY', 'NZAA', '4567', 'YSSY DCT NZAA'),
    ('1A2B3C', 'QZ004', 'RJTT', 'VHHH', '6710', 'RJTT DCT VHHH'),
    ('FE9876', 'HD005', 'ENSB', 'ENTC', '0420', 'ENSB DCT ENTC'),
    ('C0FFEE', 'ED006', 'NFFN', 'NTAA', '7654', 'NFFN DCT NTAA'),
]
c.executemany('INSERT INTO flight_metadata VALUES (?,?,?,?,?,?)', flight_data)

random.seed(42)
for icao in [r[0] for r in aircraft_data]:
    for t in range(5):
        ts = f"2024-01-15T12:{t*10:02d}:00Z"
        sig = round(-85.0 + random.uniform(-5, 5), 1)
        rng = round(random.uniform(10, 200), 1)
        c.execute(
            'INSERT INTO surveillance_history '
            '(icao, timestamp_utc, signal_dbm, range_nm, receiver_id) '
            'VALUES (?,?,?,?,?)',
            (icao, ts, sig, rng, 'RX001')
        )

db.commit()
db.close()
print("Database created at /app/aircraft.db")
