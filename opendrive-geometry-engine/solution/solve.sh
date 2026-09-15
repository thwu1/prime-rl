#!/usr/bin/env bash

pip3 install asam-qc-opendrive==1.0.0 lxml==5.3.0 -q

# Run the cross-standard analysis pipeline (QC report + entity positions)
python3 /solution/solve_pipeline.py

# Copy the geometry query engine
cp /solution/odr_eval.py /app/odr_eval.py
chmod +x /app/odr_eval.py
