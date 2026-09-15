#!/bin/bash

# Part 1: Fix tc_generator.py bugs and run it
python3 /solution/solve_helper.py

# Part 2: Run the multi-interface HTB analyzer
cp /solution/tc_analyzer.py /app/tc_analyzer.py
python3 /app/tc_analyzer.py

# Part 3: Generate nftables classification rules
python3 /solution/nft_generator.py
