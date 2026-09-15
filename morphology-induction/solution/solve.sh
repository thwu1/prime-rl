#!/bin/bash

cd /app

# Decompress genome sequences
gunzip -k /app/data/genome_sequences.fasta.gz 2>/dev/null || true

# Extract batch QC reports from tar archive
tar xzf /app/data/batch_reports.tar.gz -C /tmp/

# Run the solver
python3 /solution/solver.py
