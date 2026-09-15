#!/bin/bash
set -e

echo "=== Satellite Imagery Cloud Cover Scoring Pipeline ==="
echo ""

# Step 1: Generate synthetic test data
echo "[1/4] Generating synthetic test data..."
python scripts/generate_data.py
echo ""

# Step 2: Run baseline cloud detection submission
echo "[2/4] Running baseline cloud detection..."
python submission_src/main.py
echo ""

# Step 3: Validate prediction format
echo "[3/4] Validating prediction format..."
python -m pytest tests/test_submission.py -v
echo ""

# Step 4: Score predictions against ground truth
echo "[4/4] Computing IoU scores..."
python scripts/metric.py predictions data/test_labels results/score.json
echo ""

echo "=== Pipeline complete ==="
echo "Results saved to results/score.json"
