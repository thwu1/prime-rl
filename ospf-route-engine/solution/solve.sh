#!/bin/bash

pip3 install scapy==2.5.0 -q
cd /app
python3 /solution/compute_routes.py
