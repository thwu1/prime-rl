#!/bin/bash

cp /solution/pipeline.py /app/analyze.py
cp /solution/Makefile /app/Makefile
make -C /app all
