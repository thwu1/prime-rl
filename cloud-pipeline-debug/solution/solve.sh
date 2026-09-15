#!/bin/bash

pip3 install numpy==2.1.3 Pillow==11.1.0 -q

# Step 1: Fix all structural bugs in the pipeline files
python3 /solution/apply_fixes.py

# Step 2: Run fixed calibration to produce calibrated TOA data
cd /app && python3 pipeline/calibrate.py

# Step 3: Analyze calibrated data against ground truth to derive
# classification thresholds and generate classify.py
python3 /solution/derive_classifier.py

# Step 4: Run the complete pipeline (calibrate + classify + validate + score)
bash /app/run_pipeline.sh
