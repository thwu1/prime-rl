#!/bin/bash

pip3 install h5py==3.11.0 numpy==1.26.4 -q

cd /app
python3 /solution/analyzer.py
