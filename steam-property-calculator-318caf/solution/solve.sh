#!/bin/bash

cd /app/src

# Fix C source bugs and Makefile using helper script
python3 /solution/fix_and_build.py

# Install the CLI
cp /solution/if97_impl.py /app/if97
chmod +x /app/if97
