#!/bin/bash

cp /solution/co2_eos_impl.py /app/co2_eos.py
cp /solution/compute_cycle_impl.py /app/compute_cycle.py
cp /solution/Makefile_impl /app/Makefile
cp /solution/cycle_plot.gp /app/cycle_plot.gp

cd /app && make all
