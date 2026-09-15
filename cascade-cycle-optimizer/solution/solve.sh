#!/bin/bash

export PIP_BREAK_SYSTEM_PACKAGES=1
python3 -m pip install CoolProp==8.0.0 numpy==2.1.3 scipy==1.14.1 -q 2>&1

cp /solution/cascade_solution.py /app/cascade.py
