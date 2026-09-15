#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Generate input data
python3 /app/setup_data.py

# Install reference solution
cp /solution/cdspec.py /app/cdspec
chmod +x /app/cdspec
