#!/bin/bash

cp /solution/evaluator_impl.py /app/evaluator.py
python3 /solution/generate_makefile.py
cd /app
make all
