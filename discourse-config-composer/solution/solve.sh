#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Solution: copy the reference implementation into place
cp /solution/compose_solution.py /app/compose.py
chmod +x /app/compose.py
