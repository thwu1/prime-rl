#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/gauss_impl.py /app/gauss_basis/__init__.py

cd /app && python3 run_pipeline.py
