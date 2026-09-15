#!/bin/bash

# Install optional momepy dependencies required for diversity metrics
pip3 install mapclassify==2.8.0 inequality==1.0.1 -q

python3 /solution/compute_morphometrics.py
