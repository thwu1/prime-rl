#!/bin/bash

cd /app
mkdir -p scripts
cp /solution/Makefile.ref /app/Makefile
cp /solution/pipeline.py /app/scripts/pipeline.py
make -C /app all
