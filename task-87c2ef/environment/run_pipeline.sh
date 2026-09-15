#!/bin/bash
set -e
cd /app
echo "=== Running Evaluation Pipeline ==="
python3 /app/evaluator/evaluate.py

if [ -f /app/output/leaderboard.json ]; then
    echo ""
    echo "=== Output Summary ==="
    echo "Top-level keys:"
    jq 'keys' /app/output/leaderboard.json
    echo ""
    echo "Final ranking:"
    jq '.final_ranking' /app/output/leaderboard.json
    echo ""
    echo "Team metrics (team_e - no segmentation submission):"
    jq '.team_metrics.team_e' /app/output/leaderboard.json
    echo ""
    echo "Sample rankings (team_a):"
    jq '.rankings.team_a' /app/output/leaderboard.json
else
    echo "ERROR: leaderboard.json not produced"
    exit 1
fi
