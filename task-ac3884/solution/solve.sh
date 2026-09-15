#!/bin/bash

# No extra pip deps needed — solution uses only Python stdlib.
cp /solution/server.py /app/server.py
chmod +x /app/server.py
echo "Deployed server.py to /app/"
