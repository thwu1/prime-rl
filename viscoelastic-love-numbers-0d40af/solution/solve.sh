#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/propagator.py /app/love_numbers.py
cd /app
python3 /app/love_numbers.py
