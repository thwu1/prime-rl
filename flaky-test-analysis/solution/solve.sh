#!/bin/bash

cp /solution/analyzer.py /app/flaky_analyzer.py
cd /app && python3 flaky_analyzer.py
