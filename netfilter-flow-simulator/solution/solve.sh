#!/bin/bash

pip3 install scapy==2.5.0 -q

cp /solution/analyzer.py /app/analyzer.py

cd /app
python3 /app/analyzer.py
