#!/usr/bin/env bash

set -e

pip3 install scapy==2.6.1 -q

cd /app
python3 /solution/analyze.py
