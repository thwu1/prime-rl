#!/bin/bash

set -e

pip3 install pysam==0.22.1 -q

# Ensure reference is indexed
if [ ! -f /app/reference.fa.fai ]; then
    samtools faidx /app/reference.fa
fi

# Run the analysis pipeline
python3 /solution/analyze.py
