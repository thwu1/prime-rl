#!/bin/bash

pip3 install numpy==2.1.3 gmsh==4.12.2 -q
cp /solution/analyze.py /app/analyze.py
cd /app && python3 analyze.py
