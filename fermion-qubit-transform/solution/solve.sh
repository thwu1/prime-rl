#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.13.1 pyyaml==6.0.2 -q

# Patch all project files (Makefile, config, source code)
python3 /solution/patch_project.py

# Run the fixed pipeline via make
cd /app && make all
