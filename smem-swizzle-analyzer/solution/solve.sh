#!/bin/bash

pip3 install pyyaml==6.0.2 -q

cd /app
python3 /solution/solve.py
make -C /app clean
make -C /app all
