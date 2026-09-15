#!/bin/bash


pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/qcm_transfer.c /app/qcm_transfer.c
cp /solution/Makefile /app/Makefile
cp /solution/qcm_analysis.py /app/qcm_analysis.py
cp /solution/qcm_cli.py /app/qcm_cli.py

cd /app
make all
