#!/bin/bash

pip3 install numpy==1.26.4 -q

cp /solution/engine_impl.py /app/engine.py
cd /app
python3 -c "from engine import run_all; run_all()"
