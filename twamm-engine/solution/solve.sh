#!/usr/bin/env bash

# Compile C library
cd /app/lib && make

# Create SQLite database from SQL dump
sqlite3 /app/data/twamm.db < /app/data/init.sql

# Install solution
cp /solution/twamm_engine.py /app/twamm_engine.py
