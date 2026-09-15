#!/usr/bin/env bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Compile the Fortran spectral feedback library into a shared object
gfortran -shared -fPIC -O2 -o /app/libspectral.so /app/data/spectral_feedback.f90

cd /app
python3 /solution/reactor_kinetics.py
