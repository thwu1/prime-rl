#!/usr/bin/env python3
"""Run the QARTOD QC pipeline."""

import sys
sys.path.insert(0, "/app")
from qc_engine import run_pipeline

run_pipeline("/app/config.yaml", "/app/sensor_data.csv", "/app/output/flags.json")
