#!/bin/bash

pip3 install numpy==2.0.2 scipy==1.14.1 -q

cp /solution/solve.py /app/pipeline.py
cd /app
python3 /app/pipeline.py
