#!/bin/bash

set -e

# Install solution dependencies
pip3 install -q setuptools==75.6.0

# Run the exploit builder
python3 /solution/exploit_builder.py
