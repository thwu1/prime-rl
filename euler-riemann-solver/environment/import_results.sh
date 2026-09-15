#!/bin/bash
# Import simulation results into SQLite database

DB=/app/results/results.db
rm -f "$DB"

# Create tables
sqlite3 "$DB" "CREATE TABLE sod (x REAL, density REAL, velocity REAL, pressure REAL);"
sqlite3 "$DB" "CREATE TABLE einfeldt (x REAL, density REAL, velocity REAL, pressure REAL);"
sqlite3 "$DB" "CREATE TABLE blast (x REAL, density REAL, velocity REAL, pressure REAL);"
sqlite3 "$DB" "CREATE TABLE convergence (resolution INTEGER, dx REAL, l1_error REAL);"

# Import data
sqlite3 "$DB" ".import /app/results/sod.csv sod"
sqlite3 "$DB" ".import /app/results/einfeldt.csv einfeldt"
sqlite3 "$DB" ".import /app/results/blast.csv blast"
sqlite3 "$DB" ".import /app/results/convergence_data.csv convergence"
