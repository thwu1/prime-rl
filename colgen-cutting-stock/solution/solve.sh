#!/bin/bash

pip3 install scipy==1.13.0 PuLP==2.7.0 numpy==1.26.4 -q

cd /app
python3 /solution/solve_cutstock.py
