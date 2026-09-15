#!/bin/bash

set -e

pip3 install clevercsv==0.8.5 chardet==5.2.0 regex==2024.11.6 -q

python3 /solution/solver.py
