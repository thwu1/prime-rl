#!/bin/bash

pip3 install numpy==2.1.3 netCDF4==1.7.2 -q

# Install the reference snow model and report generator
cp /solution/snow_model.py /app/snow_model.py
cp /solution/generate_report.py /app/generate_report.py
chmod +x /app/snow_model.py /app/generate_report.py

echo "Snow model and report generator installed at /app/"
