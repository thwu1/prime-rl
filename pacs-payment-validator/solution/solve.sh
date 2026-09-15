#!/bin/bash

set -euo pipefail

# Copy the reference implementation into /app
cp /solution/validator_impl.py /app/validator.py
chmod +x /app/validator.py
