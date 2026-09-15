#!/bin/bash

# Deploy the BagIt validator
cp /solution/bagit_validator.py /app/bagit-validate
chmod +x /app/bagit-validate

# Repair damaged archives and generate forensic report
python3 /solution/repair_bags.py
