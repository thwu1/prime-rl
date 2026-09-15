#!/bin/bash

pip3 install scipy==1.13.1 -q

cd /app
cp /solution/drift_monitor.py /app/drift_monitor.py
python3 /app/drift_monitor.py
