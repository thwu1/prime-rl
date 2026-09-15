#!/bin/bash

pip3 install numpy==2.1.3 scikit-learn==1.6.0 -q
cp /solution/solve.py /app/pipeline.py
python3 /app/pipeline.py
