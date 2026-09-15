#!/bin/bash

pip3 install stim==1.14.0 pymatching==2.2.1 numpy==1.26.4 scipy==1.14.1 -q

cd /app
python3 /solution/analysis.py
