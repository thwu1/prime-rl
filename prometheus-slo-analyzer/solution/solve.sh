#!/bin/bash

cd /app
cp /solution/analyzer.py /app/analyzer.py
cp /solution/rules_gen.py /app/rules_gen.py
python3 /app/analyzer.py
python3 /app/rules_gen.py
