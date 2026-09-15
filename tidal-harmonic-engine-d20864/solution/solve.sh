#!/bin/bash

pip3 install numpy==2.1.3 -q

python3 /solution/fix_engine.py

cd /app/libastro && make clean && make
