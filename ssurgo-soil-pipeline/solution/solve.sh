#!/bin/bash

pip3 install requests==2.32.3 -q

# Deploy solution
cp /solution/soil_report.py /app/soil_report.py
chmod +x /app/soil_report.py
