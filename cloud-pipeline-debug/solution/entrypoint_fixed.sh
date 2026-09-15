#!/bin/bash
# Fixed entrypoint: removed set -e, fixed test path, added mkdir for predictions
set -uxo pipefail
exit_code=0

{
    cd /app

    echo "=== Cloud Cover Detection Pipeline ==="
    echo "$(date): Starting pipeline..."

    mkdir -p /app/predictions

    echo "Running submission code..."
    python3 submission_src/main.py

    echo "Validating submission outputs..."
    python3 -m pytest -v /app/tests/test_submission.py
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo "Computing IoU metric..."
        python3 /app/scripts/metric.py
        exit_code=$?
    fi

    echo "$(date): Pipeline complete"
    echo "=== END ==="
} |& tee "/app/submission/log.txt"

exit $exit_code
