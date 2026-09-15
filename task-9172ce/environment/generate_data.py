#!/usr/bin/env python3
"""
Generate monitoring database, reference docs, pipe-delimited standards file,
XML monitor registry, and per-state erroneous report archive for NAAQS
compliance audit task.

"""
import sqlite3
import json
import os
import tarfile
import io

DB_PATH = "/app/monitoring.db"
DOCS_DIR = "/app/docs"
AUDIT_DIR = "/app/audit"
OUTPUT_DIR = "/app/output"
DATA_DIR = "/app/data"

# ── Site Metadata ───────────────────────────────────────────────────
# (state_code, county_code, site_num, lat, lon, site_name, address,
#  state_name, county_name, city_name, cbsa_name)
SITES = {
    'AZ': ('04', '013', '3002', 33.503, -112.095,
           'SOUTH PHOENIX', '33 W TAMARISK AVE',
           'Arizona', 'Maricopa', 'Phoenix', 'Phoenix-Mesa-Scottsdale, AZ'),
    'CA_SB': ('06', '071', '0306', 34.135, -117.275,
              'FONTANA', '14360 ARROW BLVD',
              'California', 'San Bernardino', 'Fontana', 'Riverside-San Bernardino-Ontario, CA'),
    'PA': ('42', '003', '0008', 40.465, -79.961,
           'LAWRENCEVILLE', '301 39TH STREET BLDG 7',
           'Pennsylvania', 'Allegheny', 'Pittsburgh', 'Pittsburgh, PA'),
    'CA_LA': ('06', '037', '1103', 34.067, -118.227,
              'LOS ANGELES-N MAIN', '1630 N MAIN ST',
              'California', 'Los Angeles', 'Los Angeles', 'Los Angeles-Long Beach-Anaheim, CA'),
    'OH': ('39', '035', '0060', 41.472, -81.681,
           'GT CRAIG', '4600 DETROIT AVE',
           'Ohio', 'Cuyahoga', 'Cleveland', 'Cleveland-Elyria, OH'),
    'TX': ('48', '201', '1039', 29.734, -95.258,
           'HOUSTON DEER PARK', '4514 1/2 DURANT ST',
           'Texas', 'Harris', 'Deer Park', 'Houston-The Woodlands-Sugar Land, TX'),
    'MO': ('29', '099', '0019', 38.283, -90.378,
           'HERCULANEUM', '891 MAIN ST',
           'Missouri', 'Jefferson', 'Herculaneum', 'St. Louis, MO-IL'),
    'CA_IMP': ('06', '025', '0005', 32.792, -115.562,
               'CALEXICO-ETHEL', '1029 ETHEL ST',
               'California', 'Imperial', 'Calexico', 'El Centro, CA'),
    'NY': ('36', '061', '0056', 40.816, -73.902,
           'IS 52', '681 KELLY ST',
           'New York', 'New York', 'New York', 'New York-Newark-Jersey City, NY-NJ-PA'),
    'TX_DAL': ('48', '113', '0069', 32.819, -96.860,
               'DALLAS HINTON', '1415 HINTON ST',
               'Texas', 'Dallas', 'Dallas', 'Dallas-Fort Worth-Arlington, TX'),
}

O3_METHOD = 'INSTRUMENTAL - ULTRA VIOLET ABSORPTION'
PM25_METHOD = 'R & P Model 2025 PM-2.5 Sequential w/WINS'
PM25_TEOM_METHOD = 'TEOM - CONTINUOUS PM2.5'
PM10_METHOD = 'HI-VOL-SA/GM-GRAVIMETRIC'
NO2_METHOD = 'INSTRUMENTAL - CHEMILUMINESCENCE'
SO2_METHOD = 'INSTRUMENTAL - ULTRAVIOLET FLUORESCENCE'


def create_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE monitors (
        monitor_id INTEGER PRIMARY KEY,
        state_code TEXT NOT NULL,
        county_code TEXT NOT NULL,
        site_num TEXT NOT NULL,
        parameter_code INTEGER NOT NULL,
        poc INTEGER NOT NULL,
        latitude REAL, longitude REAL, datum TEXT,
        parameter_name TEXT, sample_duration TEXT, method_name TEXT,
        site_name TEXT, address TEXT,
        state_name TEXT, county_name TEXT, city_name TEXT, cbsa_name TEXT
    )""")

    c.execute("""CREATE TABLE annual_data (
        data_id INTEGER PRIMARY KEY,
        monitor_id INTEGER NOT NULL REFERENCES monitors(monitor_id),
        pollutant_standard TEXT NOT NULL,
        metric_used TEXT,
        year INTEGER NOT NULL,
        units TEXT,
        event_type TEXT DEFAULT 'No Events',
        observation_count INTEGER,
        observation_percent REAL,
        completeness_indicator TEXT DEFAULT 'Y',
        valid_day_count INTEGER,
        required_day_count INTEGER DEFAULT 365,
        exceptional_data_count INTEGER DEFAULT 0,
        null_data_count INTEGER DEFAULT 0,
        primary_exceedance_count INTEGER DEFAULT 0,
        secondary_exceedance_count INTEGER DEFAULT 0,
        certification_indicator TEXT DEFAULT 'Certified',
        num_obs_below_mdl INTEGER DEFAULT 0,
        arithmetic_mean REAL,
        arithmetic_standard_dev REAL,
        first_max_value REAL, first_max_datetime TEXT,
        second_max_value REAL, second_max_datetime TEXT,
        third_max_value REAL, third_max_datetime TEXT,
        fourth_max_value REAL, fourth_max_datetime TEXT,
        first_no_max_value REAL, first_no_max_datetime TEXT,
        second_no_max_value REAL, second_no_max_datetime TEXT,
        pct_99th REAL, pct_98th REAL, pct_95th REAL, pct_90th REAL,
        pct_75th REAL, pct_50th REAL, pct_10th REAL,
        date_of_last_change TEXT
    )""")

    # ── Insert Monitors ─────────────────────────────────────────────
    # (monitor_id, site_key, param_code, poc, param_name, sample_dur, method)
    monitors = [
        (1,  'AZ',      44201, 1, 'Ozone',                    '8-HR RUN AVG BEGIN HOUR', O3_METHOD),
        (2,  'CA_SB',   44201, 1, 'Ozone',                    '8-HR RUN AVG BEGIN HOUR', O3_METHOD),
        (3,  'PA',      44201, 1, 'Ozone',                    '8-HR RUN AVG BEGIN HOUR', O3_METHOD),
        (4,  'PA',      44201, 2, 'Ozone',                    '8-HR RUN AVG BEGIN HOUR', O3_METHOD),
        (5,  'CA_LA',   88101, 1, 'PM2.5 - Local Conditions', '24 HOUR',                 PM25_METHOD),
        (6,  'PA',      88101, 1, 'PM2.5 - Local Conditions', '24 HOUR',                 PM25_METHOD),
        (7,  'OH',      88101, 1, 'PM2.5 - Local Conditions', '24 HOUR',                 PM25_METHOD),
        (8,  'NY',      88101, 1, 'PM2.5 - Local Conditions', '24 HOUR',                 PM25_METHOD),
        (9,  'TX',      42602, 1, 'Nitrogen dioxide (NO2)',   '1 HOUR',                  NO2_METHOD),
        (10, 'MO',      42401, 1, 'Sulfur dioxide',           '1 HOUR',                  SO2_METHOD),
        (11, 'AZ',      81102, 1, 'PM10 Total 0-10um STP',   '24 HOUR',                 PM10_METHOD),
        (12, 'CA_IMP',  81102, 1, 'PM10 Total 0-10um STP',   '24 HOUR',                 PM10_METHOD),
        (13, 'TX_DAL',  88101, 1, 'PM2.5 - Local Conditions', '24 HOUR',                 PM25_TEOM_METHOD),
    ]
    for mid, sk, pc, poc, pn, sd, meth in monitors:
        s = SITES[sk]
        c.execute("INSERT INTO monitors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, s[0], s[1], s[2], pc, poc, s[3], s[4], 'NAD83',
                   pn, sd, meth, s[5], s[6], s[7], s[8], s[9], s[10]))

    # ── Insert Annual Data ──────────────────────────────────────────
    did = [0]  # mutable counter

    def ins(mid, std, metric, yr, units, evt, comp,
            obs, pct, vd, pex, sex, mean, sd,
            m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10):
        did[0] += 1
        lc = f'{yr+1}-05-15'
        c.execute("""INSERT INTO annual_data (
            data_id, monitor_id, pollutant_standard, metric_used, year, units,
            event_type, observation_count, observation_percent, completeness_indicator,
            valid_day_count, null_data_count,
            primary_exceedance_count, secondary_exceedance_count,
            arithmetic_mean, arithmetic_standard_dev,
            first_max_value, first_max_datetime,
            second_max_value, second_max_datetime,
            third_max_value, third_max_datetime,
            fourth_max_value, fourth_max_datetime,
            pct_99th, pct_98th, pct_95th, pct_90th,
            pct_75th, pct_50th, pct_10th,
            date_of_last_change
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (did[0], mid, std, metric, yr, units, evt, obs, pct, comp,
             vd, 365 - vd, pex, sex, mean, sd,
             m1, f'{yr}-06-15 14:00', m2, f'{yr}-07-22 15:00',
             m3, f'{yr}-08-03 13:00', m4, f'{yr}-06-28 14:00',
             p99, p98, p95, p90, p75, p50, p10, lc))

    # ═══════════════════════════════════════════════════════════════
    # Monitor 1: AZ O3 POC 1  (04-013-3002)
    # 4th max: 0.072, 0.068, 0.071 → avg=0.07033 → trunc(3dp)=0.070
    # ═══════════════════════════════════════════════════════════════
    ins(1, 'Ozone 8-hour 2015', 'Daily Maximum', 2022, 'Parts per million', 'No Events', 'Y',
        351, 96.2, 351, 3, 3, 0.048, 0.012,
        0.087, 0.082, 0.078, 0.072, 0.082, 0.078, 0.069, 0.064, 0.055, 0.047, 0.032)
    ins(1, 'Ozone 8-hour 2015', 'Daily Maximum', 2023, 'Parts per million', 'No Events', 'Y',
        358, 98.1, 358, 0, 0, 0.046, 0.011,
        0.079, 0.075, 0.071, 0.068, 0.075, 0.071, 0.065, 0.060, 0.052, 0.045, 0.030)
    ins(1, 'Ozone 8-hour 2015', 'Daily Maximum', 2024, 'Parts per million', 'No Events', 'Y',
        355, 97.3, 355, 2, 2, 0.047, 0.012,
        0.085, 0.080, 0.075, 0.071, 0.080, 0.075, 0.067, 0.062, 0.054, 0.046, 0.031)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 2: CA O3 POC 1  (06-071-0306)
    # 4th max: 0.081, 0.079, 0.076 → avg=0.07866 → trunc(3dp)=0.078
    # ═══════════════════════════════════════════════════════════════
    ins(2, 'Ozone 8-hour 2015', 'Daily Maximum', 2022, 'Parts per million', 'Events Included', 'Y',
        349, 95.6, 349, 12, 12, 0.056, 0.018,
        0.102, 0.095, 0.088, 0.081, 0.095, 0.088, 0.079, 0.073, 0.065, 0.053, 0.035)
    # Events Excluded distractor for 2022 — different 4th max value
    ins(2, 'Ozone 8-hour 2015', 'Daily Maximum', 2022, 'Parts per million', 'Events Excluded', 'Y',
        349, 95.6, 342, 5, 5, 0.052, 0.015,
        0.095, 0.088, 0.081, 0.072, 0.088, 0.081, 0.072, 0.066, 0.058, 0.049, 0.033)
    ins(2, 'Ozone 8-hour 2015', 'Daily Maximum', 2023, 'Parts per million', 'No Events', 'Y',
        361, 98.9, 361, 9, 9, 0.054, 0.016,
        0.098, 0.091, 0.085, 0.079, 0.091, 0.085, 0.076, 0.070, 0.062, 0.051, 0.033)
    ins(2, 'Ozone 8-hour 2015', 'Daily Maximum', 2024, 'Parts per million', 'No Events', 'Y',
        355, 97.3, 355, 7, 7, 0.053, 0.015,
        0.092, 0.087, 0.081, 0.076, 0.087, 0.081, 0.073, 0.068, 0.060, 0.050, 0.032)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 3: PA O3 POC 1  (42-003-0008)
    # 4th max (2015): 0.067, 0.069, 0.068 → avg=0.068 → trunc=0.068
    # Also has Ozone 8-hour 2008 distractor records
    # ═══════════════════════════════════════════════════════════════
    for std in ['Ozone 8-hour 2015', 'Ozone 8-hour 2008']:
        ins(3, std, 'Daily Maximum', 2022, 'Parts per million', 'No Events', 'Y',
            340, 93.2, 340, 1, 1, 0.042, 0.011,
            0.078, 0.074, 0.071, 0.067, 0.074, 0.071, 0.063, 0.058, 0.049, 0.041, 0.028)
        ins(3, std, 'Daily Maximum', 2023, 'Parts per million', 'No Events', 'Y',
            352, 96.4, 352, 1, 1, 0.044, 0.012,
            0.082, 0.076, 0.073, 0.069, 0.076, 0.073, 0.065, 0.060, 0.051, 0.043, 0.029)
        ins(3, std, 'Daily Maximum', 2024, 'Parts per million', 'No Events', 'Y',
            348, 95.3, 348, 1, 1, 0.043, 0.011,
            0.080, 0.075, 0.072, 0.068, 0.075, 0.072, 0.064, 0.059, 0.050, 0.042, 0.028)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 4: PA O3 POC 2 (distractor — different 4th max values)
    # 4th max: 0.071, 0.073, 0.072 → would give DV=0.072 if used
    # ═══════════════════════════════════════════════════════════════
    ins(4, 'Ozone 8-hour 2015', 'Daily Maximum', 2022, 'Parts per million', 'No Events', 'Y',
        338, 92.6, 338, 2, 2, 0.044, 0.012,
        0.082, 0.078, 0.074, 0.071, 0.078, 0.074, 0.066, 0.061, 0.052, 0.043, 0.029)
    ins(4, 'Ozone 8-hour 2015', 'Daily Maximum', 2023, 'Parts per million', 'No Events', 'Y',
        350, 95.9, 350, 2, 2, 0.046, 0.013,
        0.086, 0.080, 0.077, 0.073, 0.080, 0.077, 0.068, 0.063, 0.054, 0.045, 0.030)
    ins(4, 'Ozone 8-hour 2015', 'Daily Maximum', 2024, 'Parts per million', 'No Events', 'Y',
        345, 94.5, 345, 1, 1, 0.045, 0.012,
        0.084, 0.079, 0.075, 0.072, 0.079, 0.075, 0.067, 0.062, 0.053, 0.044, 0.029)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 5: LA PM2.5 POC 1  (06-037-1103)
    # Annual 2024: means 10.1, 9.8, 9.5 → avg=9.8 → round1=9.8 → Exceeding
    # 24-hr 2006: 98th pctl 38.2, 36.1, 35.7 → avg=36.67 → round=37 → Exceeding
    # Also has PM25 Annual 2012 distractor
    # ═══════════════════════════════════════════════════════════════
    pm25_la = {
        2022: (351, 96.2, 351, 2, 2, 10.1, 4.2, 42.5, 39.8, 38.6, 37.1, 40.2, 38.2, 34.5, 28.1, 14.8, 8.9, 3.2),
        2023: (358, 98.1, 358, 1, 1, 9.8,  3.8, 39.1, 37.5, 36.8, 35.4, 38.0, 36.1, 32.2, 26.5, 13.9, 8.5, 2.9),
        2024: (355, 97.3, 355, 1, 1, 9.5,  3.5, 38.4, 36.9, 36.1, 34.8, 37.2, 35.7, 31.8, 25.8, 13.5, 8.2, 2.7),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm25_la.items():
        for std in ['PM25 Annual 2024', 'PM25 Annual 2012']:
            ins(5, std, 'Observed Values', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
                obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)
        ins(5, 'PM25 24-hour 2006', 'Daily Mean', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 6: PA PM2.5 POC 1  (42-003-0008)
    # Annual 2024: means 9.2, 8.8, 9.1 → avg=9.033 → round1=9.0 → Meeting
    # 24-hr 2006: 98th pctl 34.1, 33.5, 32.9 → avg=33.5 → round=34 → Meeting
    # ═══════════════════════════════════════════════════════════════
    pm25_pa = {
        2022: (348, 95.3, 348, 0, 0, 9.2, 3.9, 35.8, 34.5, 34.2, 33.8, 35.2, 34.1, 30.5, 24.2, 12.8, 8.1, 2.5),
        2023: (355, 97.3, 355, 0, 0, 8.8, 3.5, 34.2, 33.9, 33.6, 33.1, 34.0, 33.5, 29.8, 23.5, 12.2, 7.8, 2.3),
        2024: (350, 95.9, 350, 0, 0, 9.1, 3.7, 35.5, 34.8, 33.5, 33.0, 34.5, 32.9, 29.2, 23.8, 12.5, 7.9, 2.4),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm25_pa.items():
        for std in ['PM25 Annual 2024', 'PM25 Annual 2012']:
            ins(6, std, 'Observed Values', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
                obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)
        ins(6, 'PM25 24-hour 2006', 'Daily Mean', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 7: OH PM2.5 POC 1  (39-035-0060)
    # Annual 2024: means 8.5, 8.9, 8.7 → avg=8.7 → round1=8.7 → Meeting
    # 24-hr 2006: 98th pctl 34.5, 36.8, 35.2 → avg=35.5 → round=36 → Exceeding
    # ═══════════════════════════════════════════════════════════════
    pm25_oh = {
        2022: (345, 94.5, 345, 0, 0, 8.5, 3.6, 37.2, 36.1, 35.4, 34.8, 36.5, 34.5, 29.8, 23.5, 11.9, 7.4, 2.1),
        2023: (360, 98.6, 360, 2, 2, 8.9, 3.8, 41.5, 39.2, 37.8, 36.5, 39.5, 36.8, 31.2, 25.1, 12.5, 7.8, 2.3),
        2024: (352, 96.4, 352, 1, 1, 8.7, 3.7, 39.8, 37.5, 36.2, 35.5, 37.8, 35.2, 30.5, 24.2, 12.2, 7.6, 2.2),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm25_oh.items():
        for std in ['PM25 Annual 2024', 'PM25 Annual 2012']:
            ins(7, std, 'Observed Values', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
                obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)
        ins(7, 'PM25 24-hour 2006', 'Daily Mean', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 8: NY PM2.5 POC 1  (36-061-0056)
    # 2023 INCOMPLETE → Insufficient Data
    # ═══════════════════════════════════════════════════════════════
    pm25_ny = {
        2022: ('Y', 345, 94.5, 345, 0, 0, 8.5, 3.2, 28.5, 26.8, 25.2, 24.5, 27.1, 25.5, 22.8, 18.5, 11.2, 7.5, 2.8),
        2023: ('N', 185, 50.7, 185, 0, 0, 7.2, 2.8, 22.5, 21.2, 20.1, 19.5, 21.8, 20.5, 18.2, 15.1,  9.5, 6.5, 2.2),
        2024: ('Y', 350, 95.9, 350, 0, 0, 8.8, 3.4, 30.2, 28.5, 27.1, 26.2, 28.8, 27.5, 24.5, 19.8, 12.0, 7.8, 3.0),
    }
    for yr, (comp, obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm25_ny.items():
        for std in ['PM25 Annual 2024', 'PM25 Annual 2012']:
            ins(8, std, 'Observed Values', yr, 'Micrograms/cubic meter (LC)', 'No Events', comp,
                obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)
        ins(8, 'PM25 24-hour 2006', 'Daily Mean', yr, 'Micrograms/cubic meter (LC)', 'No Events', comp,
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 9: TX NO2 POC 1  (48-201-1039)
    # 98th pctl: 95, 102, 98 → avg=98.33 → round=98 → Meeting
    # ═══════════════════════════════════════════════════════════════
    no2_tx = {
        2022: (8520, 97.3, 355, 0, 0, 15.2, 12.8, 148, 135, 122, 118, 105, 95, 78, 62, 38, 12, 2),
        2023: (8680, 99.1, 362, 0, 0, 16.1, 13.5, 155, 142, 128, 121, 118, 102, 82, 65, 40, 13, 2),
        2024: (8590, 98.1, 358, 0, 0, 15.8, 13.1, 152, 138, 125, 119, 112, 98, 80, 63, 39, 12, 2),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in no2_tx.items():
        ins(9, 'NO2 1-hour 2010', 'Daily Maximum', yr, 'Parts per billion', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 10: MO SO2 POC 1  (29-099-0019)
    # 99th pctl: 78, 72, 76 → avg=75.33 → round=75 → Meeting
    # 98th pctl: 62, 58, 60 (used by the erroneous previous report)
    # ═══════════════════════════════════════════════════════════════
    so2_mo = {
        2022: (8450, 96.5, 352, 0, 0, 4.8, 8.2, 185, 162, 148, 135, 78, 62, 42, 28, 12, 2, 0),
        2023: (8610, 98.3, 359, 0, 0, 4.2, 7.5, 168, 155, 138, 125, 72, 58, 38, 25, 10, 2, 0),
        2024: (8540, 97.5, 356, 0, 0, 4.5, 7.8, 175, 158, 142, 130, 76, 60, 40, 26, 11, 2, 0),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in so2_mo.items():
        ins(10, 'SO2 1-hour 2010', 'Daily Maximum', yr, 'Parts per billion', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 11: AZ PM10 POC 1  (04-013-3002)
    # Exceedance counts: 2, 1, 0 → avg=1.0 → Meeting (≤1)
    # ═══════════════════════════════════════════════════════════════
    pm10_az = {
        2022: (360, 98.6, 360, 2, 2, 58.2, 32.5, 198, 175, 162, 148, 155, 142, 120, 98, 72, 52, 22),
        2023: (355, 97.3, 355, 1, 1, 52.8, 28.1, 168, 145, 138, 125, 142, 130, 108, 88, 65, 48, 20),
        2024: (358, 98.1, 358, 0, 0, 48.5, 25.2, 142, 128, 118, 108, 125, 115, 95, 78, 58, 44, 18),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm10_az.items():
        ins(11, 'PM10 24-hour 2006', 'Observed Values', yr, 'Micrograms/cubic meter (25 C)', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 12: CA PM10 POC 1  (06-025-0005)
    # Exceedance counts: 3, 2, 4 → avg=3.0 → Exceeding
    # ═══════════════════════════════════════════════════════════════
    pm10_ca = {
        2022: (358, 98.1, 358, 3, 3, 72.5, 45.2, 285, 245, 218, 195, 210, 185, 155, 128, 92, 62, 25),
        2023: (352, 96.4, 352, 2, 2, 68.1, 42.8, 262, 228, 198, 182, 195, 172, 145, 118, 85, 58, 23),
        2024: (360, 98.6, 360, 4, 4, 75.8, 48.5, 312, 268, 235, 208, 228, 198, 168, 138, 98, 65, 28),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm10_ca.items():
        ins(12, 'PM10 24-hour 2006', 'Observed Values', yr, 'Micrograms/cubic meter (25 C)', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    # ═══════════════════════════════════════════════════════════════
    # Monitor 13: TX DAL PM2.5 POC 1  (48-113-0069) — ARM method
    # This monitor uses an Approved Regional Method (non-regulatory).
    # It has valid data but must be excluded based on XML registry.
    # Annual 2024: means 8.2, 8.5, 8.3 → avg=8.33 → round1=8.3
    # 24-hr 2006: 98th pctl 32.1, 33.5, 31.8 → avg=32.47 → round=32
    # ═══════════════════════════════════════════════════════════════
    pm25_dal = {
        2022: (345, 94.5, 345, 0, 0, 8.2, 3.1, 34.5, 33.2, 32.8, 32.1, 33.8, 32.1, 28.5, 22.8, 11.5, 7.2, 2.5),
        2023: (355, 97.3, 355, 0, 0, 8.5, 3.3, 36.2, 34.8, 34.1, 33.5, 35.2, 33.5, 29.8, 24.1, 12.1, 7.5, 2.7),
        2024: (350, 95.9, 350, 0, 0, 8.3, 3.2, 35.1, 33.8, 32.5, 31.8, 34.2, 31.8, 28.2, 23.2, 11.8, 7.3, 2.6),
    }
    for yr, (obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10) in pm25_dal.items():
        for std in ['PM25 Annual 2024', 'PM25 Annual 2012']:
            ins(13, std, 'Observed Values', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
                obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)
        ins(13, 'PM25 24-hour 2006', 'Daily Mean', yr, 'Micrograms/cubic meter (LC)', 'No Events', 'Y',
            obs, pct, vd, pex, sex, mean, sd, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10)

    conn.commit()
    conn.close()
    print(f"Created {DB_PATH} with 13 monitors and {did[0]} annual data records")


# ── NAAQS Regulatory Reference Document ────────────────────────────
REFERENCE_DOC = r"""EPA NATIONAL AMBIENT AIR QUALITY STANDARDS (NAAQS)
DESIGN VALUE AND ATTAINMENT DETERMINATION - REGULATORY REFERENCE
==============================================================
Office of Air Quality Planning and Standards
40 CFR Part 50, Appendices A-U

1. SCOPE AND APPLICABILITY
--------------------------------------------------------------

National Ambient Air Quality Standards (NAAQS) are established under
Sections 108-109 of the Clean Air Act for criteria pollutants. Compliance
is assessed by computing design values from ambient monitoring data
collected through the Air Quality System (AQS). A design value is a
pollutant-specific statistic computed from three consecutive years of
certified monitoring data.


2. MONITOR ELIGIBILITY
--------------------------------------------------------------

2.1  Method Designation
     Only monitors operating under methods designated as Federal Reference
     Methods (FRM) or Federal Equivalent Methods (FEM) per 40 CFR Part 53
     are eligible for NAAQS compliance determinations. Data from monitors
     using Approved Regional Methods (ARM), non-reference methods, or
     special purpose methods are excluded from regulatory assessments.

     Method designations are maintained in the AQS monitoring network
     configuration registry — they are NOT stored in annual summary data
     files. The registry must be consulted to determine each monitor's
     method classification.

2.2  Parameter Occurrence Code (POC)
     When multiple monitors exist at the same site for the same parameter,
     the primary monitor (POC 1) is used for NAAQS compliance.

2.3  Event Type Classification
     Annual summary records carry event type classifications:
       - "No Events" — no exceptional events during the period
       - "Events Included" — exceptional event data retained
       - "Events Excluded" — recalculated with exceptional event data removed

     For NAAQS compliance determination, use "No Events" or "Events
     Included" records. "Events Excluded" records serve exceptional event
     demonstrations under 40 CFR 50.14 and must NOT be used for standard
     compliance assessment.


3. CURRENT STANDARDS AND DESIGN VALUE METHODOLOGY
--------------------------------------------------------------

3.1  Ozone (O3), Parameter Code 44201
     Standard: 0.070 ppm, 8-hour averaging time (2015)
     The design value is the 3-year average of the annual 4th-highest
     daily maximum 8-hour concentration.

     Decimal convention: Ozone design values are TRUNCATED (not rounded)
     to three decimal places per 40 CFR Part 50 Appendix U. Example:
     0.07549 → 0.075. All digits beyond the third decimal are dropped.

     The 2015 standard supersedes the 2008 standard (0.075 ppm).

3.2  Fine Particulate Matter (PM2.5), Parameter Code 88101

     Annual Standard (2024): 9.0 ug/m3
       Design value: 3-year average of annual weighted arithmetic means.
       Reported to 1 decimal place, standard arithmetic rounding.
       Supersedes the 2012 annual standard (12.0 ug/m3).

     24-Hour Standard (2006): 35 ug/m3
       Design value: 3-year average of annual 98th percentile values.
       Reported as integer, standard arithmetic rounding.

3.3  Coarse Particulate Matter (PM10), Parameter Code 81102
     24-Hour Standard (2006): 150 ug/m3
     PM10 uses a distinctive compliance form based on expected exceedance
     frequency. The standard is met when the expected number of days per
     calendar year with a 24-hour concentration exceeding 150 ug/m3 is
     no more than one, averaged over 3 years.

     IMPORTANT: Compliance is NOT determined by comparing a concentration
     statistic to 150. It is determined by whether the 3-year average of
     annual exceedance counts exceeds one.

3.4  Nitrogen Dioxide (NO2), Parameter Code 42602
     1-Hour Standard (2010): 100 ppb
     Design value: 3-year average of the annual 98th percentile of daily
     maximum 1-hour concentrations.
     Reported as integer, standard arithmetic rounding.

3.5  Sulfur Dioxide (SO2), Parameter Code 42401
     1-Hour Standard (2010): 75 ppb
     Design value: 3-year average of the annual 99th percentile of daily
     maximum 1-hour concentrations.
     Reported as integer, standard arithmetic rounding.

     NOTE: SO2 uses the 99th percentile, distinct from NO2 which uses the
     98th percentile.


4. ROUNDING CONVENTIONS
--------------------------------------------------------------

4.1  Standard Arithmetic Rounding ("Round Half Up")
     Unless otherwise specified (see Ozone truncation in Section 3.1),
     EPA uses standard arithmetic rounding:
       - digit >= 5 at the rounding position → round up
       - digit < 5 → truncate

     Examples: 35.5 → 36; 35.4 → 35; 9.05 → 9.1; 9.04 → 9.0

     IMPORTANT: Python's built-in round() uses banker's rounding (round
     half to even), which differs from EPA convention. Implementers must
     account for this difference.

4.2  Ozone truncation is described in Section 3.1.


5. DATA COMPLETENESS
--------------------------------------------------------------

A valid design value requires adequate data completeness for each of the
three years in the assessment period. AQS data includes a completeness
indicator: "Y" indicates minimum criteria met, "N" indicates insufficient
data. If any year has inadequate completeness, the design value cannot be
validly computed.


6. SUPERSEDED STANDARDS
--------------------------------------------------------------

AQS data may contain records evaluated against both current and previously
superseded standards. Only current standards are used for compliance:
  - Ozone 8-hour 2015   (current; supersedes 2008)
  - PM25 Annual 2024     (current; supersedes 2012)
  - PM25 24-hour 2006    (current)
  - PM10 24-hour 2006    (current)
  - NO2 1-hour 2010      (current)
  - SO2 1-hour 2010      (current)
"""


def create_reference_doc():
    os.makedirs(DOCS_DIR, exist_ok=True)
    path = os.path.join(DOCS_DIR, "naaqs_design_value_guidance.txt")
    with open(path, 'w') as f:
        f.write(REFERENCE_DOC)
    print(f"Created {path}")


def create_monitor_xml():
    """Create XML monitor network configuration registry.

    Contains method designations (FRM/FEM/ARM) and monitor objectives
    for all monitors. The ARM monitor (48-113-0069) must be excluded
    from regulatory compliance assessment.
    """
    xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<aqs:MonitoringNetwork xmlns:aqs="http://www.epa.gov/aqs/monitoring/2.0"
                       xmlns:geo="http://www.epa.gov/aqs/geo/1.0"
                       version="2.0" exportDate="2025-01-15">
  <aqs:Region regionCode="9" regionName="Pacific Southwest">
    <aqs:MonitoringSite stateCode="04" countyCode="013" siteNumber="3002">
      <aqs:SiteName>SOUTH PHOENIX</aqs:SiteName>
      <geo:Location latitude="33.503" longitude="-112.095" datum="NAD83"/>
      <aqs:Monitor parameterCode="44201" poc="1">
        <aqs:ParameterName>Ozone</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="1998-01-15"/>
        <aqs:SamplingFrequency>CONTINUOUS</aqs:SamplingFrequency>
      </aqs:Monitor>
      <aqs:Monitor parameterCode="81102" poc="1">
        <aqs:ParameterName>PM10 Total 0-10um STP</aqs:ParameterName>
        <aqs:MethodDesignation>FEM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2001-05-22"/>
        <aqs:SamplingFrequency>EVERY 6TH DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
    <aqs:MonitoringSite stateCode="06" countyCode="025" siteNumber="0005">
      <aqs:SiteName>CALEXICO-ETHEL</aqs:SiteName>
      <geo:Location latitude="32.792" longitude="-115.562" datum="NAD83"/>
      <aqs:Monitor parameterCode="81102" poc="1">
        <aqs:ParameterName>PM10 Total 0-10um STP</aqs:ParameterName>
        <aqs:MethodDesignation>FEM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2005-03-08"/>
        <aqs:SamplingFrequency>EVERY 6TH DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
    <aqs:MonitoringSite stateCode="06" countyCode="037" siteNumber="1103">
      <aqs:SiteName>LOS ANGELES-N MAIN</aqs:SiteName>
      <geo:Location latitude="34.067" longitude="-118.227" datum="NAD83"/>
      <aqs:Monitor parameterCode="88101" poc="1">
        <aqs:ParameterName>PM2.5 - Local Conditions</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="1999-07-01"/>
        <aqs:SamplingFrequency>EVERY 3RD DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
    <aqs:MonitoringSite stateCode="06" countyCode="071" siteNumber="0306">
      <aqs:SiteName>FONTANA</aqs:SiteName>
      <geo:Location latitude="34.135" longitude="-117.275" datum="NAD83"/>
      <aqs:Monitor parameterCode="44201" poc="1">
        <aqs:ParameterName>Ozone</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="1997-04-15"/>
        <aqs:SamplingFrequency>CONTINUOUS</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
  </aqs:Region>
  <aqs:Region regionCode="2" regionName="Northeast">
    <aqs:MonitoringSite stateCode="36" countyCode="061" siteNumber="0056">
      <aqs:SiteName>IS 52</aqs:SiteName>
      <geo:Location latitude="40.816" longitude="-73.902" datum="NAD83"/>
      <aqs:Monitor parameterCode="88101" poc="1">
        <aqs:ParameterName>PM2.5 - Local Conditions</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2002-09-15"/>
        <aqs:SamplingFrequency>EVERY 3RD DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
  </aqs:Region>
  <aqs:Region regionCode="3" regionName="Mid-Atlantic">
    <aqs:MonitoringSite stateCode="42" countyCode="003" siteNumber="0008">
      <aqs:SiteName>LAWRENCEVILLE</aqs:SiteName>
      <geo:Location latitude="40.465" longitude="-79.961" datum="NAD83"/>
      <aqs:Monitor parameterCode="44201" poc="1">
        <aqs:ParameterName>Ozone</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="1996-02-28"/>
        <aqs:SamplingFrequency>CONTINUOUS</aqs:SamplingFrequency>
      </aqs:Monitor>
      <aqs:Monitor parameterCode="44201" poc="2">
        <aqs:ParameterName>Ozone</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2003-06-15"/>
        <aqs:SamplingFrequency>CONTINUOUS</aqs:SamplingFrequency>
      </aqs:Monitor>
      <aqs:Monitor parameterCode="88101" poc="1">
        <aqs:ParameterName>PM2.5 - Local Conditions</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2000-01-01"/>
        <aqs:SamplingFrequency>EVERY 3RD DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
  </aqs:Region>
  <aqs:Region regionCode="5" regionName="Great Lakes">
    <aqs:MonitoringSite stateCode="39" countyCode="035" siteNumber="0060">
      <aqs:SiteName>GT CRAIG</aqs:SiteName>
      <geo:Location latitude="41.472" longitude="-81.681" datum="NAD83"/>
      <aqs:Monitor parameterCode="88101" poc="1">
        <aqs:ParameterName>PM2.5 - Local Conditions</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2001-03-01"/>
        <aqs:SamplingFrequency>EVERY 3RD DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
  </aqs:Region>
  <aqs:Region regionCode="6" regionName="South Central">
    <aqs:MonitoringSite stateCode="48" countyCode="201" siteNumber="1039">
      <aqs:SiteName>HOUSTON DEER PARK</aqs:SiteName>
      <geo:Location latitude="29.734" longitude="-95.258" datum="NAD83"/>
      <aqs:Monitor parameterCode="42602" poc="1">
        <aqs:ParameterName>Nitrogen dioxide (NO2)</aqs:ParameterName>
        <aqs:MethodDesignation>FEM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2010-01-01"/>
        <aqs:SamplingFrequency>CONTINUOUS</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
    <aqs:MonitoringSite stateCode="48" countyCode="113" siteNumber="0069">
      <aqs:SiteName>DALLAS HINTON</aqs:SiteName>
      <geo:Location latitude="32.819" longitude="-96.860" datum="NAD83"/>
      <aqs:Monitor parameterCode="88101" poc="1">
        <aqs:ParameterName>PM2.5 - Local Conditions</aqs:ParameterName>
        <aqs:MethodDesignation>ARM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SPM</aqs:MonitorObjective>
        <aqs:MonitorType>NON-REGULATORY</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2019-03-10"/>
        <aqs:SamplingFrequency>EVERY 3RD DAY</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
  </aqs:Region>
  <aqs:Region regionCode="7" regionName="Central">
    <aqs:MonitoringSite stateCode="29" countyCode="099" siteNumber="0019">
      <aqs:SiteName>HERCULANEUM</aqs:SiteName>
      <geo:Location latitude="38.283" longitude="-90.378" datum="NAD83"/>
      <aqs:Monitor parameterCode="42401" poc="1">
        <aqs:ParameterName>Sulfur dioxide</aqs:ParameterName>
        <aqs:MethodDesignation>FRM</aqs:MethodDesignation>
        <aqs:MonitorObjective>SLAMS</aqs:MonitorObjective>
        <aqs:MonitorType>CRITERIA</aqs:MonitorType>
        <aqs:OperationalStatus active="true" startDate="2005-08-15"/>
        <aqs:SamplingFrequency>CONTINUOUS</aqs:SamplingFrequency>
      </aqs:Monitor>
    </aqs:MonitoringSite>
  </aqs:Region>
</aqs:MonitoringNetwork>
'''
    path = os.path.join(DATA_DIR, "monitor_config.xml")
    with open(path, 'w') as f:
        f.write(xml_content)
    print(f"Created {path}")


def create_previous_reports_archive():
    """Create per-state previous (erroneous) compliance reports as tar.gz archive.

    Planted errors:
    A) O3 rounding: Used round() instead of truncation for 06-071-0306 -> 0.079 not 0.078
    B) Old PM2.5 Annual standard: Used "PM25 Annual 2012" (NAAQS=12.0) instead of
       "PM25 Annual 2024" (NAAQS=9.0) for all PM2.5 annual entries
    C) SO2 wrong percentile: Used 98th percentile instead of 99th -> DV=60 not 75
    D) No completeness check: Computed DV for 36-061-0056 despite incomplete 2023 data
    E) PM10 threshold: Compared exceedance count to 150 (concentration level) instead
       of 1 (exceedance threshold)
    """
    state_monitors = {
        "04": {
            "state_name": "Arizona",
            "monitors": [
                {"site_id": "04-013-3002", "parameter_code": 44201,
                 "parameter_name": "Ozone", "pollutant_standard": "Ozone 8-hour 2015",
                 "design_value": 0.070, "naaqs_level": 0.070, "units": "ppm",
                 "status": "Meeting"},
                {"site_id": "04-013-3002", "parameter_code": 81102,
                 "parameter_name": "PM10 Total 0-10um STP",
                 "pollutant_standard": "PM10 24-hour 2006",
                 "design_value": 1.0, "naaqs_level": 150.0,
                 "units": "Micrograms/cubic meter (25 C)", "status": "Meeting"},
            ]
        },
        "06": {
            "state_name": "California",
            "monitors": [
                {"site_id": "06-025-0005", "parameter_code": 81102,
                 "parameter_name": "PM10 Total 0-10um STP",
                 "pollutant_standard": "PM10 24-hour 2006",
                 "design_value": 3.0, "naaqs_level": 150.0,
                 "units": "Micrograms/cubic meter (25 C)", "status": "Meeting"},
                {"site_id": "06-037-1103", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 24-hour 2006",
                 "design_value": 37.0, "naaqs_level": 35.0, "units": "ug/m3",
                 "status": "Exceeding"},
                {"site_id": "06-037-1103", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 Annual 2012",
                 "design_value": 9.8, "naaqs_level": 12.0, "units": "ug/m3",
                 "status": "Meeting"},
                {"site_id": "06-071-0306", "parameter_code": 44201,
                 "parameter_name": "Ozone",
                 "pollutant_standard": "Ozone 8-hour 2015",
                 "design_value": 0.079, "naaqs_level": 0.070, "units": "ppm",
                 "status": "Exceeding"},
            ]
        },
        "29": {
            "state_name": "Missouri",
            "monitors": [
                {"site_id": "29-099-0019", "parameter_code": 42401,
                 "parameter_name": "Sulfur dioxide",
                 "pollutant_standard": "SO2 1-hour 2010",
                 "design_value": 60.0, "naaqs_level": 75.0, "units": "ppb",
                 "status": "Meeting"},
            ]
        },
        "36": {
            "state_name": "New York",
            "monitors": [
                {"site_id": "36-061-0056", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 24-hour 2006",
                 "design_value": 25.0, "naaqs_level": 35.0, "units": "ug/m3",
                 "status": "Meeting"},
                {"site_id": "36-061-0056", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 Annual 2012",
                 "design_value": 8.2, "naaqs_level": 12.0, "units": "ug/m3",
                 "status": "Meeting"},
            ]
        },
        "39": {
            "state_name": "Ohio",
            "monitors": [
                {"site_id": "39-035-0060", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 24-hour 2006",
                 "design_value": 36.0, "naaqs_level": 35.0, "units": "ug/m3",
                 "status": "Exceeding"},
                {"site_id": "39-035-0060", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 Annual 2012",
                 "design_value": 8.7, "naaqs_level": 12.0, "units": "ug/m3",
                 "status": "Meeting"},
            ]
        },
        "42": {
            "state_name": "Pennsylvania",
            "monitors": [
                {"site_id": "42-003-0008", "parameter_code": 44201,
                 "parameter_name": "Ozone",
                 "pollutant_standard": "Ozone 8-hour 2015",
                 "design_value": 0.068, "naaqs_level": 0.070, "units": "ppm",
                 "status": "Meeting"},
                {"site_id": "42-003-0008", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 24-hour 2006",
                 "design_value": 34.0, "naaqs_level": 35.0, "units": "ug/m3",
                 "status": "Meeting"},
                {"site_id": "42-003-0008", "parameter_code": 88101,
                 "parameter_name": "PM2.5 - Local Conditions",
                 "pollutant_standard": "PM25 Annual 2012",
                 "design_value": 9.0, "naaqs_level": 12.0, "units": "ug/m3",
                 "status": "Meeting"},
            ]
        },
        "48": {
            "state_name": "Texas",
            "monitors": [
                {"site_id": "48-201-1039", "parameter_code": 42602,
                 "parameter_name": "Nitrogen dioxide (NO2)",
                 "pollutant_standard": "NO2 1-hour 2010",
                 "design_value": 98.0, "naaqs_level": 100.0, "units": "ppb",
                 "status": "Meeting"},
            ]
        },
    }

    os.makedirs(AUDIT_DIR, exist_ok=True)
    archive_path = os.path.join(AUDIT_DIR, "state_reports.tar.gz")

    with tarfile.open(archive_path, "w:gz") as tar:
        for fips in sorted(state_monitors.keys()):
            data = state_monitors[fips]
            content = json.dumps({
                "state_code": fips,
                "state_name": data["state_name"],
                "generated_by": "AQS Automated Compliance System v2.1",
                "generated_date": "2025-03-15",
                "assessment_period": "2022-2024",
                "monitors": data["monitors"]
            }, indent=2).encode('utf-8')
            info = tarfile.TarInfo(name=f"state_reports/{fips}.json")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

    print(f"Created {archive_path} with {len(state_monitors)} state report files")


def create_naaqs_standards_psv():
    """Create pipe-separated NAAQS standards reference file.

    Contains both current and superseded standards. Current standards
    have an empty superseded_by field. Does NOT include database column
    mappings — the solver must determine the mapping from the statistical
    form description and database schema exploration.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    header = "parameter_code|parameter_name|pollutant_standard|naaqs_level|naaqs_units|averaging_time|statistical_form|decimal_reporting|compliance_method|superseded_by"
    rows = [
        "44201|Ozone|Ozone 8-hour 2008|0.075|ppm|8-hour|3-yr avg of annual 4th highest daily max|truncate_3dp|compare_dv_to_level|Ozone 8-hour 2015",
        "44201|Ozone|Ozone 8-hour 2015|0.070|ppm|8-hour|3-yr avg of annual 4th highest daily max|truncate_3dp|compare_dv_to_level|",
        "88101|PM2.5|PM25 Annual 2012|12.0|ug/m3|Annual|3-yr avg of annual arithmetic mean|round_1dp|compare_dv_to_level|PM25 Annual 2024",
        "88101|PM2.5|PM25 Annual 2024|9.0|ug/m3|Annual|3-yr avg of annual arithmetic mean|round_1dp|compare_dv_to_level|",
        "88101|PM2.5|PM25 24-hour 2006|35.0|ug/m3|24-hour|3-yr avg of annual 98th percentile|round_int|compare_dv_to_level|",
        "81102|PM10|PM10 24-hour 2006|150.0|ug/m3|24-hour|3-yr avg of annual exceedance count|none|exceedance_count_le_1|",
        "42602|NO2|NO2 1-hour 2010|100.0|ppb|1-hour|3-yr avg of annual 98th percentile|round_int|compare_dv_to_level|",
        "42401|SO2|SO2 1-hour 2010|75.0|ppb|1-hour|3-yr avg of annual 99th percentile|round_int|compare_dv_to_level|",
    ]

    path = os.path.join(DATA_DIR, "naaqs_standards.psv")
    with open(path, 'w') as f:
        f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')

    print(f"Created {path}")


if __name__ == '__main__':
    for d in [os.path.dirname(DB_PATH), DOCS_DIR, AUDIT_DIR, OUTPUT_DIR, DATA_DIR]:
        os.makedirs(d, exist_ok=True)
    create_database()
    create_reference_doc()
    create_monitor_xml()
    create_previous_reports_archive()
    create_naaqs_standards_psv()
    print("Setup complete.")
