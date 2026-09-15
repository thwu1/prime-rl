#!/bin/bash

# Install runtime dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 scikit-learn==1.6.0 -q

# Apply bug fixes
python3 /solution/fix_bugs.py
