#!/bin/bash

# No external pip dependencies needed - uses only Python standard library

# Copy the parser to /app/ and run it
cp /solution/nnue_helper.py /app/nnue_parser.py
python3 /app/nnue_parser.py
