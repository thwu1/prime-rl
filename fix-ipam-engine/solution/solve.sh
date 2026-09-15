#!/bin/bash

pip3 install netaddr==1.3.0 -q

# Run the allocation planner
python3 /solution/allocator.py
