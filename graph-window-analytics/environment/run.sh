#!/bin/bash

# Run the network analysis pipeline
set -e

rm -f /app/network.db
sqlite3 /app/network.db < /app/schema.sql
sqlite3 /app/network.db < /app/analyze.sql

echo "Pipeline completed successfully."
