#!/bin/bash

pip3 install bartiq==0.17.0 qref==0.11.0 sympy==1.13.3 pydantic==2.10.3 -q

python3 /solution/build_and_evaluate.py
