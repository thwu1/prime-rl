#!/usr/bin/env bash

set -e

DB=/app/results.db

rm -f "$DB"

sqlite3 "$DB" "
CREATE TABLE enclosures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    geometry TEXT NOT NULL
);
CREATE TABLE view_factors (
    enclosure_id INTEGER REFERENCES enclosures(id),
    surface_from TEXT NOT NULL,
    surface_to TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (enclosure_id, surface_from, surface_to)
);
CREATE TABLE surface_results (
    enclosure_id INTEGER REFERENCES enclosures(id),
    name TEXT NOT NULL,
    area REAL NOT NULL,
    emissivity REAL NOT NULL,
    bc_type TEXT NOT NULL,
    bc_value REAL NOT NULL,
    radiosity REAL,
    net_heat_flux REAL,
    equilibrium_temp REAL,
    PRIMARY KEY (enclosure_id, name)
);
"

for enc in /app/enclosures/*.json; do
    python3 /app/radiosity_solver.py "$enc" "$DB"
done

echo "Pipeline complete. Results in $DB"
