#!/bin/bash

set -e

cd /app

# Install project dependencies
npm install --silent 2>&1

# Apply fixes to the generator
python3 /solution/fix_generator.py

# Run the codegen with the fixed generator
npx tsx /app/src/codegen.ts

# Verify the output compiles
npx tsc --noEmit --strict --target ES2022 --module node16 --moduleResolution node16 /app/generated/types.ts

echo "Solution applied and verified successfully."
