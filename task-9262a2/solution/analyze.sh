#!/bin/bash

set -e

DB="/app/results.db"
RUBRICS="/app/data/rubrics"
GRADES="/app/data/grades"
ENGINE="/app/rubric_engine.py"

# Remove stale database
rm -f "$DB"

# Create tables
sqlite3 "$DB" "CREATE TABLE scores(paper TEXT PRIMARY KEY, leaf_count INTEGER, score REAL);"
sqlite3 "$DB" "CREATE TABLE stratified(paper TEXT, category TEXT, contribution REAL, coverage REAL, conditional_score REAL, PRIMARY KEY(paper, category));"
sqlite3 "$DB" "CREATE TABLE optimal_depths(epsilon REAL PRIMARY KEY, depth INTEGER, max_error REAL);"
sqlite3 "$DB" "CREATE TABLE bounds(paper TEXT PRIMARY KEY, current_score REAL, min_score REAL, max_score REAL, max_swing REAL);"

# Process each rubric/grade pair
for rubric_file in "$RUBRICS"/*.json; do
    name=$(basename "$rubric_file" .json)
    grades_file="$GRADES/${name}.json"

    [ -f "$grades_file" ] || continue

    # Validate rubric structure with jq
    if ! jq -e '.id and .weight and .sub_tasks' "$rubric_file" > /dev/null 2>&1; then
        echo "SKIP: $rubric_file failed validation" >&2
        continue
    fi

    # Count leaves with jq
    leaf_count=$(jq '[.. | objects | select(.sub_tasks == [])] | length' "$rubric_file")

    # Compute score
    score=$(python3 "$ENGINE" score --rubric "$rubric_file" --grades "$grades_file" | jq '.replication_score')

    sqlite3 "$DB" "INSERT INTO scores VALUES ('$name', $leaf_count, $score);"

    # Compute stratified scores and insert via jq parsing
    strat_json=$(python3 "$ENGINE" stratified-score --rubric "$rubric_file" --grades "$grades_file")

    echo "$strat_json" | jq -r '.categories | to_entries[] | "\(.key)|\(.value.contribution)|\(.value.coverage)|\(.value.conditional_score)"' | while IFS='|' read -r cat contrib cov cond; do
        sqlite3 "$DB" "INSERT INTO stratified VALUES ('$name', '$cat', $contrib, $cov, $cond);"
    done

    # Extract Result Match leaf IDs and compute score-bounds
    uncertain=$(jq -r '[.. | objects | select(.task_category == "Result Match") | .id] | join(",")' "$rubric_file")
    if [ -n "$uncertain" ]; then
        bounds_json=$(python3 "$ENGINE" score-bounds --rubric "$rubric_file" --grades "$grades_file" --uncertain "$uncertain")
        cs=$(echo "$bounds_json" | jq '.current_score')
        mn=$(echo "$bounds_json" | jq '.min_score')
        mx=$(echo "$bounds_json" | jq '.max_score')
        sw=$(echo "$bounds_json" | jq '.max_swing')
        sqlite3 "$DB" "INSERT INTO bounds VALUES ('$name', $cs, $mn, $mx, $sw);"
    fi
done

# Compute optimal depths for several epsilon values
for eps in 0.06 0.04 0.025 0.01; do
    result=$(python3 "$ENGINE" optimal-depth --rubrics-dir "$RUBRICS" --grades-dir "$GRADES" --epsilon "$eps")
    depth=$(echo "$result" | jq '.optimal_depth')
    max_err=$(echo "$result" | jq '.max_error')
    sqlite3 "$DB" "INSERT INTO optimal_depths VALUES ($eps, $depth, $max_err);"
done

echo "Pipeline complete. Database at $DB"
