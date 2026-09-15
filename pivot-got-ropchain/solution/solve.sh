#!/bin/bash

pip3 install pwntools==4.12.0 -q
cp /solution/solve.py /app/exploit.py
python3 /app/exploit.py
