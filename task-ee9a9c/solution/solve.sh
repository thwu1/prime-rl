#!/bin/bash

# Install solution dependencies
pip3 install bcrypt==4.2.1 -q

# Run the credential forensics pipeline
python3 /solution/crack_pipeline.py
