#!/bin/bash

pip3 install drain3==0.9.11 pandas==2.2.3 -q

mkdir -p /app/evaluation /app/results
cp /solution/evaluate.py /app/evaluation/evaluate.py
cp /solution/post_process.py /app/evaluation/post_process.py

python3 /solution/pipeline.py
