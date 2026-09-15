#!/bin/bash

cp /solution/fixed_init.py /app/evalue/__init__.py
cp /solution/fixed_martingales.py /app/evalue/martingales.py
cp /solution/fixed_cusum.py /app/evalue/cusum.py
cp /solution/fixed_confseq.py /app/evalue/confseq.py
cp /solution/fixed_detect.py /app/detect.py

cd /app
python3 detect.py
