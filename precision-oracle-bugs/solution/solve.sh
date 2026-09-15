#!/bin/bash

pip3 install mpmath==1.3.0 -q

cp /solution/adaptive_engine.py /app/adaptive_engine.py
python3 /app/adaptive_engine.py
