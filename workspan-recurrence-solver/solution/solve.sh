#!/bin/bash

cp /solution/completed_makefile /app/Makefile
cp /solution/solver.py /app/compute.py
cd /app && make clean && make results
