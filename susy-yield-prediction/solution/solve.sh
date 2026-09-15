#!/bin/bash

set -e
pip3 install numpy==2.1.3 pyyaml==6.0.2 -q
python3 /solution/analyze.py
