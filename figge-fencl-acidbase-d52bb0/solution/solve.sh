#!/bin/bash

mkdir -p /app/src

cp /solution/figge_core.h /app/src/figge_core.h
cp /solution/figge_core.c /app/src/figge_core.c
cp /solution/Makefile /app/Makefile
cp /solution/figge_fencl.py /app/figge_fencl.py
cp /solution/cli.py /app/cli.py

cd /app && make build
