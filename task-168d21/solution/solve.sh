#!/bin/bash

# No pip deps needed - uses only stdlib

# Generate all artifacts: AT&T FST definition, LEXC grammar, Makefile,
# lookup input, and output.txt (directly from morphology rules)
python3 /solution/build_generator.py

# Copy lookup output parser to /app
cp /solution/parse_lookup.py /app/parse_lookup.py

# Build the HFST transducer from AT&T format
cd /app && make kaltiru.hfst
