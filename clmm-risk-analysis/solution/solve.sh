#!/bin/bash

pip3 install scipy==1.14.1 -q

cp /solution/analyzer.py /app/analyzer.py
cd /app
python3 /app/analyzer.py
