#!/bin/bash

cd /app

# Install dependencies
npm install -g tsx@4.19.4 2>/dev/null

# Apply all fixes via the helper script
tsx /solution/fix.ts
