#!/bin/bash

# Install scipy for numerical utilities
pip3 install scipy==1.14.1 -q

# Deploy the fixed and extended solution
cp /solution/pr_flash_solution.py /app/pr_flash.py
chmod +x /app/pr_flash.py
