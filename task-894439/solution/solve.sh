#!/bin/bash

pip3 install pandas==2.2.3 numpy==2.1.3 scipy==1.14.1 numfracpy==0.4 -q

cp /solution/solve_calibrate.py /app/calibrate.py
python3 /app/calibrate.py
