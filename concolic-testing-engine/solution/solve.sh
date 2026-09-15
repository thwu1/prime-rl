#!/bin/bash

pip3 install z3-solver==4.13.0.0 -q

cp /solution/bugfinder.py /app/bugfinder.py
cd /app
python3 bugfinder.py
