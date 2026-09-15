#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/pipeline.py /app/pipeline.py
cd /app
python3 /app/pipeline.py
