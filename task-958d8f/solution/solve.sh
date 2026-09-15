#!/bin/bash

pip3 install pyyaml==6.0.2 -q
cp /solution/transform_engine.py /app/transform_engine.py
python3 /app/transform_engine.py
