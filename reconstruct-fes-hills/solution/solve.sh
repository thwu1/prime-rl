#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/sum_hills.py /app/sum_hills
cp /solution/preprocess.awk /app/preprocess.awk
cp /solution/converge.py /app/converge.py
cp /solution/Makefile /app/Makefile
chmod +x /app/sum_hills /app/converge.py
