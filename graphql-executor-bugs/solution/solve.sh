#!/bin/bash

cd /app && npm install --prefer-offline 2>/dev/null || npm install 2>/dev/null

cp /solution/fixed_executor.ts /app/src/executor.ts
