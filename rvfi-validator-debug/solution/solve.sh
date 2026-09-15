#!/bin/bash

pip3 install pytest==8.3.4 -q

# Fix all bugs and implement M-extension in the RVFI validator
python3 /solution/fix_validator.py
