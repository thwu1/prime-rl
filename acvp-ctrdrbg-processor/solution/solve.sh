#!/bin/bash

pip3 install pycryptodome==3.21.0 -q

# Fix Bug 1: L/N swap in derivation.py
cp /solution/fixed_derivation.py /app/drbg/derivation.py

# Fix Bug 2: encrypt-before-increment in update.py
cp /solution/fixed_update.py /app/drbg/update.py

# Fix Bug 3: missing AI clear + implement no-DF mode in core.py
cp /solution/fixed_core.py /app/drbg/core.py

# Run the corrected processor
cd /app
python3 /app/acvp_processor.py
