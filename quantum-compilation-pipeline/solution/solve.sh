#!/bin/bash

pip3 install bqskit==1.2.0 numpy==1.26.4 -q

cp /solution/cr_gate.py /app/cr_gate.py
cp /solution/rotation_pass.py /app/rotation_pass.py
cp /solution/pipeline.py /app/pipeline.py

cd /app
python3 pipeline.py
