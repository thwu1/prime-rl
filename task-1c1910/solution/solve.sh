#!/bin/bash

pip3 install numpy==2.1.3 -q

cd /app

# Stage 1: OFDM demodulation — FFT, channel estimation, equalization
python3 /solution/demodulate.py

# Stage 2: Protocol decode — demap, deinterleave, Viterbi, descramble
python3 /solution/decoder.py
