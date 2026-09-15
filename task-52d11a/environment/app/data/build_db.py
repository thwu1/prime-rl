#!/usr/bin/env python3
"""Parse geomag_2024.dat (fixed-width ASCII) into a normalized SQLite database."""
import sqlite3
import os
import sys
from datetime import datetime, timedelta

DAT_FILE = sys.argv[1] if len(sys.argv) > 1 else '/app/data/geomag_2024.dat'
DB_FILE = sys.argv[2] if len(sys.argv) > 2 else '/app/data/geomag_2024.db'

FILL_KP = 999
FILL_AP = 9999
FILL_DST = 99999
FILL_AE = 99999
FILL_F107 = 999.9
FILL_SSN = 999
FILL_QUAL = 9
FILL_IMF = 999.9
FILL_DENSITY = 999.9
FILL_SPEED = 9999.9

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

c.execute('''CREATE TABLE epoch_info (
    epoch_id INTEGER PRIMARY KEY,
    utc_timestamp TEXT NOT NULL,
    year INTEGER NOT NULL,
    day_of_year INTEGER NOT NULL,
    hour INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE geomag_indices (
    epoch_id INTEGER PRIMARY KEY REFERENCES epoch_info(epoch_id),
    kp_x10 INTEGER,
    ap_index INTEGER,
    dst_index INTEGER,
    ae_index INTEGER,
    ap_qualifier INTEGER
)''')

c.execute('''CREATE TABLE solar_activity (
    epoch_id INTEGER PRIMARY KEY REFERENCES epoch_info(epoch_id),
    f107_flux REAL,
    sunspot_number INTEGER,
    bartels_rotation INTEGER
)''')

c.execute('''CREATE TABLE solar_wind (
    epoch_id INTEGER PRIMARY KEY REFERENCES epoch_info(epoch_id),
    imf_magnitude REAL,
    proton_density REAL,
    bulk_speed REAL
)''')

epoch_id = 0
with open(DAT_FILE) as f:
    for line in f:
        parts = line.split()
        if len(parts) < 14:
            continue

        year = int(parts[0])
        doy = int(parts[1])
        hour = int(parts[2])
        bartels = int(parts[3])
        kp10 = int(parts[4])
        ap = int(parts[5])
        dst = int(parts[6])
        ae = int(parts[7])
        f107 = float(parts[8])
        ssn = int(parts[9])
        qual = int(parts[10])
        imf = float(parts[11])
        density = float(parts[12])
        speed = float(parts[13])

        dt = datetime(year, 1, 1) + timedelta(days=doy - 1, hours=hour)
        utc_ts = dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        epoch_id += 1

        c.execute('INSERT INTO epoch_info VALUES (?,?,?,?,?)',
                  (epoch_id, utc_ts, year, doy, hour))

        c.execute('INSERT INTO geomag_indices VALUES (?,?,?,?,?,?)',
                  (epoch_id,
                   None if kp10 == FILL_KP else kp10,
                   None if ap == FILL_AP else ap,
                   None if dst == FILL_DST else dst,
                   None if ae == FILL_AE else ae,
                   None if qual == FILL_QUAL else qual))

        c.execute('INSERT INTO solar_activity VALUES (?,?,?,?)',
                  (epoch_id,
                   None if abs(f107 - FILL_F107) < 0.01 else f107,
                   None if ssn == FILL_SSN else ssn,
                   None if bartels == 9999 else bartels))

        c.execute('INSERT INTO solar_wind VALUES (?,?,?,?)',
                  (epoch_id,
                   None if abs(imf - FILL_IMF) < 0.01 else imf,
                   None if abs(density - FILL_DENSITY) < 0.01 else density,
                   None if abs(speed - FILL_SPEED) < 0.1 else speed))

conn.commit()
conn.close()
print(f"Created {DB_FILE} with {epoch_id} records")
