#!/bin/bash

pip3 install edn_format==0.7.5 -q

# Copy the checker implementation to /app
cp /solution/checker.py /app/checker.py
chmod +x /app/checker.py
