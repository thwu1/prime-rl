#!/bin/bash

# Deploy the BPF analysis pipeline tools
cp /solution/bpf_extract.py /app/bpf_extract
cp /solution/bpf_analyze.py /app/bpf_analyze
cp /solution/bpf_run.py /app/bpf_run
chmod +x /app/bpf_extract /app/bpf_analyze /app/bpf_run
