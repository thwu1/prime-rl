#!/bin/bash

pip3 install numpy==2.1.3 biopython==1.84 -q

cp /solution/solver.py /app/pipeline.py
python3 /app/pipeline.py
