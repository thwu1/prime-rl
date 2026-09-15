#!/bin/bash

# Fix all defects, create cache tier, and generate architecture review
python3 /solution/fix_bugs.py

# Run the playbook to generate configs for all four tiers
cd /app && ansible-playbook playbook.yml
