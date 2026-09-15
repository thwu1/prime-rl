#!/bin/bash

set -e

pip3 install eyecite==2.7.6 courts-db==0.10.14 -q

python3 /solution/analyze.py
