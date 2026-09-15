#!/bin/bash

pip3 install landlab==2.11.0 numpy==2.1.3 -q

cp /solution/analyze.py /app/analyze.py

cd /app
python3 analyze.py
