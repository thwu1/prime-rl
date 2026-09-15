#!/bin/bash

set -e

pip3 install -q ply==3.11

cp /solution/imp_lexer.py /app/
cp /solution/imp_parser.py /app/
cp /solution/interpreter.py /app/
cp /solution/analyze.py /app/
cp /solution/run_all.py /app/
cp /solution/Makefile /app/

cd /app
make all
