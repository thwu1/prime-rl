#!/bin/bash

pip3 install numpy==1.26.4 -q
mkdir -p /app/lcnet
cp /solution/lcnet/__init__.py /app/lcnet/__init__.py
cp /solution/lcnet/taxonomy.py /app/lcnet/taxonomy.py
cp /solution/lcnet/consensus.py /app/lcnet/consensus.py
cp /solution/lcnet/metrics.py /app/lcnet/metrics.py
cp /solution/lcnet/sampling.py /app/lcnet/sampling.py
cp /solution/lcnet/scoring.py /app/lcnet/scoring.py
cp /solution/lcnet/storage.py /app/lcnet/storage.py
cp /solution/lcnet/__main__.py /app/lcnet/__main__.py
cp /solution/Makefile /app/Makefile
