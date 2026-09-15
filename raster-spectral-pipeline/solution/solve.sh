#!/bin/bash

pip3 install rasterio==1.3.10 shapely==2.0.6 numpy==1.26.4 scipy==1.13.1 -q

cp /solution/solve.py /app/suitability.py
python3 /app/suitability.py
