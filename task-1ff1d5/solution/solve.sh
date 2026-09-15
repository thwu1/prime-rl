#!/bin/bash

# Install solution dependencies
pip3 install pandas==2.2.3 pyreadstat==1.2.7 -q

# Run the SDTM construction script
python3 /solution/solve.py
