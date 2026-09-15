#!/usr/bin/env bash

# No pip dependencies needed - solution uses only Python stdlib
cp /solution/perf_analyzer.py /app/perf_analyzer.py
cd /app
python3 /app/perf_analyzer.py
