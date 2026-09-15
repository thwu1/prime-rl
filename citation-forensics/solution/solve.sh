#!/bin/bash

pip3 install pyyaml==6.0.2 -q
cp /solution/evaluate.py /app/evaluate.py
cd /app && python3 evaluate.py
