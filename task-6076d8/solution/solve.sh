#!/usr/bin/env bash

set -e
cd /app

# Step 1: Parse TRF file to JSON using trf2json
trf2json /app/tournament.trf --full --pretty > /app/tournament_parsed.json

# Step 2: Get authoritative metadata from SQLite database
TOTAL_ROUNDS=$(sqlite3 /app/players.db "SELECT value FROM tournament_meta WHERE key='total_rounds'")
CURRENT_ROUND=$(sqlite3 /app/players.db "SELECT value FROM tournament_meta WHERE key='current_round'")
INITIAL_COLOUR=$(sqlite3 /app/players.db "SELECT value FROM tournament_meta WHERE key='initial_colour'")
FORBIDDEN=$(sqlite3 /app/players.db "SELECT COUNT(*) FROM forbidden_pairs")

echo "Authoritative metadata from SQLite:"
echo "  total_rounds=$TOTAL_ROUNDS (TRF says $(jq -r '.metadata.total_rounds' /app/tournament_parsed.json))"
echo "  current_round=$CURRENT_ROUND"
echo "  initial_colour=$INITIAL_COLOUR"
echo "  forbidden_pairs=$FORBIDDEN"

# Step 3: Run pairing algorithm with correct metadata
python3 /solution/dutch_pairing.py \
    --trf-json /app/tournament_parsed.json \
    --total-rounds "$TOTAL_ROUNDS" \
    --current-round "$CURRENT_ROUND" \
    --initial-colour "$INITIAL_COLOUR" \
    --db /app/players.db \
    --output /app/round5_pairing.json

# Step 4: Validate output structure with jq
jq -e 'has("pairings") and has("bye") and (.pairings | length > 0)' \
    /app/round5_pairing.json > /dev/null

echo "Solution complete. Pairing written to /app/round5_pairing.json"
