#!/bin/bash

pip3 install z3-solver==4.12.6.0 -q

cd /app
python3 /solution/auditor.py
