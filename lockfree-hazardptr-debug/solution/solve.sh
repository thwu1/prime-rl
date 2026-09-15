#!/bin/bash

pip3 install -q setuptools==75.8.0

python3 /solution/implement_hp.py

cd /app
make clean && make
./test_concurrent
