#!/bin/bash

pip3 install pymatching==2.2.1 -q

cp /solution/stim_decoder.py /app/decoder.py
cp /solution/benchmark_impl.py /app/benchmark.py

cd /app
python3 benchmark.py
