#!/bin/bash


cd /app
gcc -shared -fPIC -o libops.so ops.c
cp /solution/pipeline_impl.py /app/pipeline.py
