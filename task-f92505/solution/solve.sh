#!/bin/bash

cd /app
python3 /solution/fix_pipeline.py
make clean && make
python3 /app/main.py
