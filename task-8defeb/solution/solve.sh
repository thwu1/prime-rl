#!/bin/bash

# Ensure dependencies
pip3 install nibabel==5.3.2 numpy==2.1.3 scipy==1.14.1 -q

python3 /solution/evaluate.py
