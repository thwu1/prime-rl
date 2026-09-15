#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

mkdir -p /app/conversion_model
cp /solution/model.py /app/conversion_model/__init__.py
cp /solution/main_entry.py /app/conversion_model/__main__.py

cd /app
python3 -m conversion_model /app/data/conversions.csv /app/results.json
