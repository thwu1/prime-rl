#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 -q

# Deploy C source and Makefile
mkdir -p /app/accel
cp /solution/shell_kernel.c /app/accel/shell_kernel.c
cp /solution/Makefile.solution /app/Makefile

# Build the C shared library
make -C /app lib

# Deploy Python modules
cp /solution/gamma_impl.py /app/gamma.py
cp /solution/qa_report_impl.py /app/qa_report.py
