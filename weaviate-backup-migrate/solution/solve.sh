#!/bin/bash

# pyyaml is already available via python3-yaml (apt) in the Dockerfile
cd /app
python3 /solution/migrate_solution.py
