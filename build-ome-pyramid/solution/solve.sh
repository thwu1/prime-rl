#!/bin/bash

pip3 install numpy==2.1.3 tifffile==2025.1.10 imagecodecs==2024.12.30 -q

cd /app
python3 /solution/assemble.py
