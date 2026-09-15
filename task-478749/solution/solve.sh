#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 scikit-learn==1.5.2 PyYAML==6.0.2 -q

cd /app
python3 /solution/solve.py
