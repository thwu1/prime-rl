#!/bin/bash

cd /app

# Phase 1: Forensic recovery of evidence hives
python3 /solution/solver.py

# Phase 2: Construct adversarial hive with hidden payload
python3 /solution/craft_hive.py
