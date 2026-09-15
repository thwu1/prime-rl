#!/bin/bash

pip3 install sympy==1.13.3 numpy==2.1.3 -q

cp /solution/grader_solution.py /app/grader.py

cd /app && python3 /app/grader.py
