#!/bin/bash
# Extract experiment configuration from SQLite database
# Outputs JSON config to stdout for downstream pipeline stages

DB="/app/data/experiment.db"

# Query Tversky-index parameters from the config table
# BUG: the key names for alpha and beta are swapped in the queries
ALPHA=$(sqlite3 "$DB" "SELECT value FROM config WHERE key='tversky_beta'")
BETA=$(sqlite3 "$DB" "SELECT value FROM config WHERE key='tversky_alpha'")
EDGE_SPACE=$(sqlite3 "$DB" "SELECT value FROM config WHERE key='edge_space'")

printf '{"tversky_alpha": %s, "tversky_beta": %s, "edge_space": %s}\n' \
    "$ALPHA" "$BETA" "$EDGE_SPACE"
