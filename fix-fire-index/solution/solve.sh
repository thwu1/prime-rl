#!/bin/bash

# Install solution dependencies
pip3 install scipy==1.14.1 numpy==2.1.3 -q

# Fix the 3 bugs in cffwis.py
python3 /solution/fix_bugs.py

# Run the extreme analysis pipeline
python3 /solution/pipeline.py
