#!/bin/bash
set -euxo pipefail
exit_code=0

{
    cd /app

    echo "=== Cloud Cover Detection Pipeline ==="
    echo "$(date): Starting pipeline..."

    echo "Running submission code..."
    python3 submission_src/main.py

    echo "Validating submission outputs..."
    python3 -m pytest -v /app/test/test_submission.py

    echo "Computing IoU metric..."
    python3 /app/scripts/metric.py

    echo "$(date): Pipeline complete"
    echo "=== END ==="
} |& tee "/app/submission/log.txt"

exit $exit_code
