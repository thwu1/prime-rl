#!/bin/bash


# Deploy engine
cp /solution/engine_impl.py /app/engine.py

# Deploy pipeline script
cp /solution/run_suite_impl.sh /app/run_suite.sh
chmod +x /app/run_suite.sh

# Deploy Makefile
cp /solution/Makefile_impl /app/Makefile

# Run the full pipeline
cd /app
make clean test report

# Verify outputs
echo "=== Verification ==="
echo "Engine UCI check:"
printf 'uci\nisready\nquit\n' | timeout 10 python3 /app/engine.py 2>/dev/null | grep -q "readyok" && echo "  PASS" || echo "  FAIL"

echo "Database row count:"
sqlite3 /app/results.db "SELECT COUNT(*) FROM results;" 2>/dev/null

echo "Report accuracy:"
jq '.accuracy' /app/report.json 2>/dev/null

echo "Pipeline deployed successfully."
