#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 pyyaml==6.0.2 -q

mkdir -p /app/src

cp /solution/phase_noise.py /app/src/phase_noise.py
cp /solution/ofdm.py /app/src/ofdm.py
cp /solution/evm_analyzer.py /app/src/evm_analyzer.py
cp /solution/analyze.py /app/src/analyze.py

python3 /app/src/analyze.py
