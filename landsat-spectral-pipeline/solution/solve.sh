#!/bin/bash

pip3 install numpy==1.26.4 rasterio==1.3.10 -q

cd /app
python3 /solution/solve.py
