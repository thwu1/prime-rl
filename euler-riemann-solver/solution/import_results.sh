#!/bin/bash
# Import simulation results into SQLite database

DB=/app/results/results.db
rm -f "$DB"

# Create tables with correct column names
sqlite3 "$DB" "CREATE TABLE sod (x REAL, rho REAL, u REAL, p REAL);"
sqlite3 "$DB" "CREATE TABLE einfeldt (x REAL, rho REAL, u REAL, p REAL);"
sqlite3 "$DB" "CREATE TABLE blast (x REAL, rho REAL, u REAL, p REAL);"
sqlite3 "$DB" "CREATE TABLE convergence (ncells INTEGER, dx REAL, l1_error REAL);"

# Import data with CSV mode and skip headers
sqlite3 "$DB" ".mode csv" ".import --skip 1 /app/results/sod.csv sod"
sqlite3 "$DB" ".mode csv" ".import --skip 1 /app/results/einfeldt.csv einfeldt"
sqlite3 "$DB" ".mode csv" ".import --skip 1 /app/results/blast.csv blast"
sqlite3 "$DB" ".mode csv" ".import --skip 1 /app/results/convergence_data.csv convergence"
