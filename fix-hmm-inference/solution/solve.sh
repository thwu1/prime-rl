#!/bin/bash

# Derive and apply fixes to the buggy HMM model, then add decoding and evaluation
pip3 install numpy==1.26.4 -q
python3 /solution/fix_model.py
