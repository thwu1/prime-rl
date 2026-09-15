#!/bin/bash

cp /solution/pipeline.py /app/pipeline.py
cp /solution/Makefile /app/Makefile
mkdir -p /app/output
cd /app && make all
