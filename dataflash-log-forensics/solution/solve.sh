#!/bin/bash

pip3 install pymavlink==2.4.41 -q

cd /app
python3 /solution/solve_helper.py
