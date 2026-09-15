-- Required database schema for multi-station ADS-B track fusion pipeline
-- All tables must be created with these exact names and column names.

CREATE TABLE IF NOT EXISTS raw_messages (
    msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    hex_raw TEXT NOT NULL,
    crc_syndrome INTEGER,
    status TEXT NOT NULL,       -- 'valid', 'corrected', or 'invalid'
    corrected_hex TEXT,
    df INTEGER,
    icao TEXT,
    type_code INTEGER
);

CREATE TABLE IF NOT EXISTS aircraft (
    icao TEXT PRIMARY KEY,
    callsign TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    pos_id INTEGER PRIMARY KEY AUTOINCREMENT,
    icao TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude INTEGER,
    source_station TEXT,
    FOREIGN KEY (icao) REFERENCES aircraft(icao)
);

CREATE TABLE IF NOT EXISTS velocities (
    vel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    icao TEXT NOT NULL,
    ground_speed REAL,
    heading REAL,
    vertical_rate INTEGER,
    source_station TEXT,
    FOREIGN KEY (icao) REFERENCES aircraft(icao)
);
