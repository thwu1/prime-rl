#!/bin/bash

set -e

# Install dependencies
pip3 install flopy==3.10.0 numpy==2.1.3 -q

# Download MODFLOW 6 binary
python3 -c "
import flopy
flopy.utils.get_modflow('/usr/local/bin')
"

# Fix model, evaluate, design wells, and run
python3 /solution/fix_and_run.py
