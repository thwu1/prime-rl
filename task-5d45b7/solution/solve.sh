#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/solver.py /app/sif_parser.py
cd /app
python3 sif_parser.py
