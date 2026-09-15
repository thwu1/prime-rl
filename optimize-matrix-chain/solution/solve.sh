#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/optimizer.py /app/optimizer.py
cd /app
python3 /app/optimizer.py
