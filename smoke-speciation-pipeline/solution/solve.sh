#!/bin/bash

pip3 install netCDF4==1.6.5 numpy==1.26.4 -q
cp /solution/speciate.py /app/speciate
chmod +x /app/speciate
cd /app && /app/speciate
