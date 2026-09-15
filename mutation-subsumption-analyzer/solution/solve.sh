#!/bin/bash

set -e

# Install dependencies
pip3 install pytest==8.3.4 -q

# Run the mutation analysis pipeline
python3 /solution/mutator.py
