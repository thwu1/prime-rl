#!/bin/bash
# Multi-spectral Land Cover Classification Pipeline
set -euxo pipefail
exit_code=0

{
    cd /app
    echo "=== Land Cover Classification Pipeline ==="
    echo "$(date): Starting pipeline..."

    echo "Stage 1: Radiometric calibration..."
    python3 pipeline/calibrate.py

    echo "Stage 2: Format validation..."
    python3 pipeline/validate.py

    echo "Stage 3: Land cover classification..."
    python3 pipeline/classify.py

    echo "Stage 4: Computing score..."
    python3 pipeline/score.py

    echo "$(date): Pipeline complete"
    echo "=== END ==="
} |& tee "/app/output/pipeline.log"

exit $exit_code
