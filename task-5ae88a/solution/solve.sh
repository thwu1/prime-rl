#!/bin/bash


cp /solution/mhd_solver.py /app/mhd_solver.py
cp /solution/plot_density.gp /app/plot_density.gp
cp /solution/Makefile /app/Makefile

cd /app
make all
