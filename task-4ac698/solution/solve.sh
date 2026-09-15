#!/usr/bin/env bash

set -e

pip3 install pyelftools==0.31 -q

cp /solution/bpf_analyzer.py /app/bpf_analyzer.py
chmod +x /app/bpf_analyzer.py
