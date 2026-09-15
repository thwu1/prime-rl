#!/bin/bash

pip3 install pyyaml==6.0.2 -q
cp /solution/evaluator_fixed.py /app/evaluator.py
cd /app
python3 /app/evaluator.py /app/data
