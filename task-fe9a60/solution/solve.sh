#!/bin/bash

cd /app

# Run the configuration analyzer and VRF designer
python3 /solution/analyzer.py

# Start FRR and validate corrected configs using vtysh
python3 /solution/validate_configs.py
