#!/usr/bin/env bash
set -euo pipefail

python3 /solution/fix_design.py
python3 /solution/create_analysis.py
python3 /solution/create_fast_alu.py
python3 /solution/create_report.py
