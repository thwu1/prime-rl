#!/usr/bin/env bash

pip3 install -q numpy==2.1.3 scipy==1.14.1

cp /solution/analyze.py /app/analyze.py
cd /app
python3 /app/analyze.py
